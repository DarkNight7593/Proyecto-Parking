"""
ParkingPro v1.0.0 — Sistema de Gestión de Estacionamiento
Punto de entrada: inicializa dependencias y lanza la ventana principal.
"""
import sys
import os
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

    ANCHO     = 1320
    ALTO      = 800
    SIDEBAR_W = 230
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
        self.geometry(f"{self.ANCHO}x{self.ALTO}")
        self.minsize(self.MIN_W, self.MIN_H)
        self.configure(fg_color=C["bg_root"])

        try:
            ico = os.path.join(BASE_DIR, "assets", "icon.ico")
            if os.path.exists(ico):
                self.iconbitmap(ico)
        except Exception:
            pass

        # ── Estado ────────────────────────────────────────────────────────
        self._panel_activo = None
        self._nav_btns: dict = {}
        self._nav_actual: str = ""

        # ── UI ────────────────────────────────────────────────────────────
        self._build_layout()
        self._navegar("principal")
        self._loop_reloj()
        self._loop_printer_status()

        if self.cfg.es_primera_vez():
            self.after(600, self._mostrar_setup)

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
        self._lbl_fecha = ctk.CTkLabel(reloj_f, text="", font=fuente(10), text_color=C["text_3"])
        self._lbl_fecha.pack(pady=(2, 0))

        ctk.CTkFrame(sb, fg_color=C["border"], height=1).pack(fill="x", padx=14, pady=(12, 4))

        # Navegación
        ctk.CTkLabel(sb, text="MENÚ PRINCIPAL", font=fuente(9),
                     text_color=C["text_3"]).pack(anchor="w", padx=18, pady=(8, 4))

        nav_items = [
            ("principal",     "🅿  Operación",    "Registro de vehículos"),
            ("reportes",      "📊  Reportes",      "Ingresos y estadísticas"),
            ("configuracion", "⚙️  Configuración", "Tarifas y ajustes"),
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
        ctk.CTkFrame(sb, fg_color=C["border"], height=1).pack(fill="x", padx=14, pady=(10, 6))
        frame_kpi = ctk.CTkFrame(sb, fg_color=C["bg_medium"], corner_radius=10)
        frame_kpi.pack(fill="x", padx=12, pady=(0, 4))
        ctk.CTkLabel(frame_kpi, text="Vehículos activos", font=fuente(10),
                     text_color=C["text_3"]).pack(anchor="w", padx=12, pady=(8, 0))
        self._lbl_activos_sb = ctk.CTkLabel(frame_kpi, text="0",
                                             font=fuente(26, bold=True), text_color=C["blue"])
        self._lbl_activos_sb.pack(padx=12, pady=(0, 8))

        # Espaciador
        ctk.CTkFrame(sb, fg_color="transparent").pack(fill="both", expand=True)

        # Estado impresora
        ctk.CTkFrame(sb, fg_color=C["border"], height=1).pack(fill="x", padx=14, pady=(0, 8))
        frame_imp = ctk.CTkFrame(sb, fg_color=C["bg_medium"], corner_radius=10)
        frame_imp.pack(fill="x", padx=12, pady=(0, 6))
        ctk.CTkLabel(frame_imp, text="🖨️  Ticketera", font=fuente(11, bold=True),
                     text_color=C["text_2"]).pack(anchor="w", padx=12, pady=(8, 2))
        self._lbl_printer = ctk.CTkLabel(frame_imp, text="...", font=fuente(10),
                                          text_color=C["text_3"])
        self._lbl_printer.pack(anchor="w", padx=12, pady=(0, 8))

        # Versión
        ctk.CTkLabel(sb, text="ParkingPro v1.0.0 © 2025",
                     font=fuente(9), text_color=C["text_3"]).pack(pady=(0, 10))

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
            )
        else:
            return

        panel.pack(fill="both", expand=True)
        self._panel_activo = panel

    def _on_config_guardada(self):
        """Recrea la instancia de Printer si cambió la impresora configurada."""
        self.printer = Printer(self.cfg.get_nombre_impresora())
        # Propagar al panel activo si lo soporta
        if hasattr(self._panel_activo, "set_printer"):
            self._panel_activo.set_printer(self.printer)

    # ─── Loops de actualización ───────────────────────────────────────────────

    def _loop_reloj(self):
        if not self.winfo_exists():
            return
        ahora = datetime.now()
        self._lbl_reloj.configure(text=ahora.strftime("%H:%M:%S"))
        self._lbl_fecha.configure(text=ahora.strftime("%a %d %b %Y").title())
        try:
            n = self.db.contar_activos()
            self._lbl_activos_sb.configure(text=str(n))
        except Exception:
            pass
        self.after(1_000, self._loop_reloj)

    def _loop_printer_status(self):
        if not self.winfo_exists():
            return
        try:
            if self.printer.esta_disponible():
                self._lbl_printer.configure(text="✓ Conectada", text_color=C["green"])
            else:
                self._lbl_printer.configure(text="✗ No detectada", text_color=C["red"])
        except Exception:
            pass
        self.after(10_000, self._loop_printer_status)

    # ─── Setup inicial ────────────────────────────────────────────────────────

    def _mostrar_setup(self):
        from ui.ventana_setup import VentanaSetup
        VentanaSetup(self, self.cfg, self.db, callback=self._post_setup)

    def _post_setup(self):
        self.printer = Printer(self.cfg.get_nombre_impresora())
        self._nav_actual = ""
        self._navegar("principal")


# ─── Arranque ─────────────────────────────────────────────────────────────────

def main():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    app = ParkingProApp()
    app.mainloop()


if __name__ == "__main__":
    main()