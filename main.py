"""
ParkingPro v1.0.0 — Sistema de Gestión de Estacionamiento
Punto de entrada: inicializa dependencias y lanza la ventana principal.
"""
import sys
import os
import threading
import customtkinter as ctk
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config_manager import ConfigManager
from database import Database
from printer import Printer
from ui.theme import C, fuente


class ParkingProApp(ctk.CTk):
    """Ventana principal: sidebar izquierdo + área de contenido."""

    MIN_W     = 1100
    MIN_H     = 680

    def __init__(self):
        super().__init__()

        # ── Dependencias ──────────────────────────────────────────────────
        self.cfg     = ConfigManager()
        self.db      = Database(self.cfg.get_db_path())
        self.db.inicializar()
        self.printer = Printer(self.cfg.get_nombre_impresora())

        # ── Ventana ───────────────────────────────────────────────────────
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.title("ParkingPro — Sistema de Estacionamiento")
        # ── Métricas de pantalla (disponibles antes de mostrar la ventana) ──
        _sw = self.winfo_screenwidth()
        _sh = self.winfo_screenheight()

        # Sidebar: 15.5% del ancho real, acotado entre 200 y 270 px
        self.SIDEBAR_W = max(200, min(270, int(_sw * 0.155)))

        # La ventana arranca en el tamaño de pantalla; state("zoomed")
        # la maximiza en Windows, pero este geometry() sirve como fallback
        # para Linux/macOS donde "zoomed" puede no funcionar igual.
        self.geometry(f"{_sw}x{_sh}+0+0")
        self.minsize(self.MIN_W, self.MIN_H)
        self.configure(fg_color=C["bg_root"])

        self.after(100, lambda: self.state("zoomed"))

        try:
            ico = os.path.join(BASE_DIR, "assets", "icon.ico")
            if os.path.exists(ico):
                self.iconbitmap(ico)
        except Exception:
            pass

        # ── AQUÍ LA PROTECCIÓN CONTRA CIERRES ─────────────────────────────
        # Interceptamos el clic en la "X" de la ventana principal
        self.protocol("WM_DELETE_WINDOW", self._intentar_cerrar_aplicacion)

        # ── Estado ────────────────────────────────────────────────────────
        self._panel_activo = None
        self._nav_btns: dict = {}
        self._nav_actual: str = ""

        # Estado actual de la impresora (actualizado cada 5 s por _loop_printer_status).
        # Cualquier panel que necesite este dato lo lee aquí; no repite la consulta WMIC.
        self._ultimo_estado_imp: dict = {"nivel": "offline", "mensaje": "Verificando..."}
        self._printer_checking = False 

        # ── UI ────────────────────────────────────────────────────────────
        self._build_layout()
        self._navegar("principal")
        self._loop_reloj()
        self._loop_printer_status()   # primera comprobación al arrancar

    # ─── Layout ──────────────────────────────────────────────────────────────

    def _build_layout(self):
        self._sidebar = ctk.CTkFrame(
            self, fg_color=C["sidebar"], width=self.SIDEBAR_W, corner_radius=0,
        )
        self._sidebar.pack(side="left", fill="y")
        self._sidebar.pack_propagate(False)

        self._content_wrap = ctk.CTkFrame(self, fg_color=C["bg_dark"], corner_radius=0)
        self._content_wrap.pack(side="left", fill="both", expand=True)

        self._build_sidebar()

    def _build_sidebar(self):
        sb = self._sidebar

        # Logo
        logo_f = ctk.CTkFrame(sb, fg_color=C["bg_dark"], height=102, corner_radius=0)
        logo_f.pack(fill="x")
        logo_f.pack_propagate(False)
        ctk.CTkLabel(logo_f, text="🅿", font=ctk.CTkFont("Helvetica", 42, weight="bold"),
                     text_color=C["blue"]).place(relx=0.5, rely=0.35, anchor="center")
        ctk.CTkLabel(logo_f, text="ParkingPro", font=fuente(16, bold=True),
                     text_color=C["text_1"]).place(relx=0.5, rely=0.73, anchor="center")

        ctk.CTkFrame(sb, fg_color=C["border"], height=1).pack(fill="x", padx=14)

        # Reloj
        reloj_f = ctk.CTkFrame(sb, fg_color="transparent")
        reloj_f.pack(fill="x", pady=(14, 2))
        self._lbl_reloj = ctk.CTkLabel(reloj_f, text="--:--:--",
                                        font=fuente(24, bold=True), text_color=C["text_1"])
        self._lbl_reloj.pack()
        self._lbl_fecha = ctk.CTkLabel(reloj_f, text="", font=fuente(10),
                                        text_color=C["text_3"])
        self._lbl_fecha.pack(pady=(2, 0))

        ctk.CTkFrame(sb, fg_color=C["border"], height=1).pack(fill="x", padx=14,
                                                                pady=(12, 4))

        # Navegación
        ctk.CTkLabel(sb, text="MENÚ PRINCIPAL", font=fuente(9),
                     text_color=C["text_3"]).pack(anchor="w", padx=18, pady=(8, 4))

        nav_items = [
            ("principal",     "🅿  Operación",    "Registro de vehículos"),
            ("reportes",      "📊  Reportes",      "Ingresos y estadísticas"),
            ("configuracion", "⚙️  Configuración", "Sistema, Tarifas y Ticketera "),
        ]
        for key, titulo, sub in nav_items:
            btn = ctk.CTkButton(
                sb,
                text=f"  {titulo}\n  {sub}",
                font=fuente(12),
                fg_color="transparent",
                hover_color=C["bg_light"],
                text_color=C["text_2"],
                anchor="w", height=62, corner_radius=10,
                command=lambda k=key: self._navegar(k),
            )
            btn.pack(fill="x", padx=8, pady=2)
            self._nav_btns[key] = btn

        # KPI activos
        ctk.CTkFrame(sb, fg_color=C["border"], height=1).pack(fill="x", padx=14,
                                                                pady=(10, 6))
        frame_kpi = ctk.CTkFrame(sb, fg_color=C["bg_medium"], corner_radius=10)
        frame_kpi.pack(fill="x", padx=12, pady=(0, 4))
        ctk.CTkLabel(frame_kpi, text="Vehículos activos", font=fuente(10),
                     text_color=C["text_3"]).pack(anchor="w", padx=12, pady=(8, 0))
        self._lbl_activos_sb = ctk.CTkLabel(frame_kpi, text="0",
                                             font=fuente(26, bold=True),
                                             text_color=C["blue"])
        self._lbl_activos_sb.pack(padx=12, pady=(0, 8))

        # ── Badge de impresora ────────────────────────────────────────────
        ctk.CTkFrame(sb, fg_color=C["border"], height=1).pack(fill="x", padx=14,
                                                                pady=(0, 6))

        self._frame_imp = ctk.CTkFrame(sb, fg_color=C["bg_medium"], corner_radius=10)
        self._frame_imp.pack(fill="x", padx=12, pady=(0, 6))

        # Fila superior: icono + título
        fila_top = ctk.CTkFrame(self._frame_imp, fg_color="transparent")
        fila_top.pack(fill="x", padx=10, pady=(8, 2))

        self._badge_printer_icon = ctk.CTkLabel(
            fila_top,
            text="🖨️",
            font=ctk.CTkFont("Helvetica", 18),
            fg_color=C["bg_dark"],
            corner_radius=6,
            width=34, height=34,
            text_color=C["text_3"],
        )
        self._badge_printer_icon.pack(side="left")

        ctk.CTkLabel(
            fila_top, text="Ticketera",
            font=fuente(11, bold=True), text_color=C["text_2"], anchor="w",
        ).pack(side="left", padx=(7, 0))

        # Fila inferior: mensaje de estado
        self._lbl_printer = ctk.CTkLabel(
            self._frame_imp,
            text="Verificando...",
            font=fuente(9),
            text_color=C["text_3"],
            anchor="w",
            wraplength=self.SIDEBAR_W - 40,   # proporcional al sidebar calculado
            justify="left",
        )
        self._lbl_printer.pack(fill="x", padx=10, pady=(0, 8))

        # Versión
        ctk.CTkLabel(sb, text="ParkingPro v1.0.0 © 2026",
                     font=fuente(9), text_color=C["text_3"]).pack(pady=(2, 8))

    # ─── Navegación ───────────────────────────────────────────────────────────

    def _navegar(self, destino: str):
        if destino == self._nav_actual:
            return
        self._nav_actual = destino

        for key, btn in self._nav_btns.items():
            activo = (key == destino)
            btn.configure(
                fg_color=C["bg_light"] if activo else "transparent",
                text_color=C["text_1"] if activo else C["text_2"],
                font=fuente(12, bold=activo),
            )

        for w in self._content_wrap.winfo_children():
            w.destroy()
        self._panel_activo = None

        if destino == "principal":
            from ui.panel_principal import PanelPrincipal
            panel = PanelPrincipal(self._content_wrap, self.cfg, self.db, self.printer)

        elif destino == "reportes":
            from ui.panel_reportes import PanelReportes
            panel = PanelReportes(self._content_wrap, self.cfg, self.db, self.printer)

        elif destino == "configuracion":
            from ui.panel_configuracion import PanelConfiguracion
            panel = PanelConfiguracion(
                self._content_wrap, self.cfg, self.db, self.printer,
                on_guardado=self._on_config_guardada,
                # Getter para que el panel lea el estado ya calculado por main,
                # sin tener que hacer su propia consulta WMIC.
                get_estado_imp=lambda: self._ultimo_estado_imp,
            )
        else:
            return

        panel.pack(fill="both", expand=True)
        self._panel_activo = panel

    def _on_config_guardada(self):
        """Recrea Printer si cambió la impresora configurada y notifica al panel activo."""
        self.printer = Printer(self.cfg.get_nombre_impresora())
        if hasattr(self._panel_activo, "set_printer"):
            self._panel_activo.set_printer(self.printer)

    # ─── Loops de actualización ───────────────────────────────────────────────

    def _loop_reloj(self):
        if not self.winfo_exists():
            return
        ahora = datetime.now()
        self._lbl_reloj.configure(text=ahora.strftime("%H:%M:%S"))
        self._lbl_fecha.configure(text=ahora.strftime("%a %d %b %Y").title())
        # Contador de activos en hilo separado, no en UI:
        threading.Thread(target=self._actualizar_contador_activos, daemon=True).start()
        self.after(1_000, self._loop_reloj)

    def _actualizar_contador_activos(self):
        try:
            n = self.db.contar_activos()
            if self.winfo_exists():
                self.after(0, lambda: self._lbl_activos_sb.configure(text=str(n)))
        except Exception:
            pass
        finally:
            self.db.cerrar_conexion_actual()

    def _loop_printer_status(self):
        if not self.winfo_exists():
            return
        if not self._printer_checking:        # ← no lanza si el anterior aún corre
            self._printer_checking = True
            def _check():
                try:
                    estado = self.printer.get_estado_detallado()
                    if self.winfo_exists():
                        self.after(0, lambda e=estado: self._apply_printer_status(e))
                except Exception:
                    pass
                finally:
                    self._printer_checking = False   # ← libera al terminar
            threading.Thread(target=_check, daemon=True).start()
        self.after(5_000, self._loop_printer_status)

    def _apply_printer_status(self, estado: dict):
        """
        Actualiza el badge del sidebar y notifica al panel activo si es Configuración.
        Guarda siempre el estado en self._ultimo_estado_imp para que cualquier panel
        pueda consultarlo sin duplicar la llamada WMIC.
        """
        if not self.winfo_exists():
            return

        # Guardar estado para que los paneles lo lean
        self._ultimo_estado_imp = estado

        nivel = estado.get("nivel", "offline")
        msg   = estado.get("mensaje", "Sin información")

        if nivel == "ok":
            card_bg    = "#0a1f12"
            icon_bg    = "#0d3321"
            icon_color = C["green"]
            txt_color  = C["green"]
        elif nivel == "warning":
            card_bg    = "#1e1500"
            icon_bg    = "#3d2e05"
            icon_color = C["yellow"]
            txt_color  = C["yellow"]
        elif nivel == "error":
            card_bg    = "#1f0707"
            icon_bg    = "#3d0a0a"
            icon_color = C["red"]
            txt_color  = C["red"]
        else:   # offline
            card_bg    = "#1f0707"
            icon_bg    = "#3d0a0a"
            icon_color = C["red"]
            txt_color  = C["red"]

        try:
            self._frame_imp.configure(fg_color=card_bg)
            self._badge_printer_icon.configure(fg_color=icon_bg, text_color=icon_color)
            self._lbl_printer.configure(text=msg, text_color=txt_color)
        except Exception:
            pass

        # Empujar estado al panel de configuración si está abierto
        if hasattr(self._panel_activo, "actualizar_estado_imp"):
            try:
                self._panel_activo.actualizar_estado_imp(estado)
            except Exception:
                pass

    # ─── NUEVO: Control de cierre seguro ──────────────────────────────────────
    def _intentar_cerrar_aplicacion(self):
        """Valida si hay procesos en segundo plano antes de destruir la app."""
        # 1. Verificar si el Modal de Cobro está procesando
        for child in self.winfo_children():
            if child.__class__.__name__ == "ModalCobro":
                if getattr(child, "_procesando", False):
                    self._mostrar_alerta_cierre()
                    return

        # 2. NUEVO: Verificar si el Panel Principal está registrando un vehículo
        if self._panel_activo and hasattr(self._panel_activo, "_registrando"):
            if self._panel_activo._registrando:
                self._mostrar_alerta_cierre()
                return

        # Si todo está libre, cerramos limpiamente
        self.destroy()
        
    def _mostrar_alerta_cierre(self):
        from tkinter import messagebox
        messagebox.showwarning(
            "Operación en curso", 
            "No puedes cerrar el programa mientras hay un registro o cobro procesándose.\n"
            "Por favor, espera unos segundos a que termine."
        )

# ─── Arranque ─────────────────────────────────────────────────────────────────

def main():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    app = ParkingProApp()
    app.mainloop()


if __name__ == "__main__":
    main()