"""
ParkingPro - Asistente de primera configuración
Pasos: Datos del negocio → Selección de ticketera → Listo

Cambios respecto a la versión anterior:
  • Paso 2 tiene scroll general + scrolls internos (lista, hardware)
  • Estado inicial: ninguna impresora seleccionada (no pre-selecciona el default)
  • Impresoras con driver no-Generic muestran botón "Cambiar Driver"
"""
import threading
import customtkinter as ctk
from tkinter import messagebox
from typing import Callable, List, Dict, Optional

from ui.theme import C, fuente
from installer import PrinterInstaller


class VentanaSetup(ctk.CTkToplevel):
    """
    Ventana de configuración inicial con 3 pasos:
      1. Datos del negocio
      2. Selección de ticketera (desde lista de impresoras instaladas)
      3. Listo / Finalizar
    """

    ANCHO = 720
    ALTO  = 660

    def __init__(self, parent, config, db, callback: Callable = None):
        super().__init__(parent)
        self.config   = config
        self.db       = db
        self.callback = callback

        self._paso_actual         = 0
        self._entries_negocio     = {}

        # ── Inicio sin impresora preseleccionada ─────────────────────────────
        # No mostramos la que viene en config (puede ser el placeholder por default)
        self._imp_seleccionada: Optional[str] = None

        self.title("ParkingPro — Configuración Inicial")
        self.geometry(f"{self.ANCHO}x{self.ALTO}")
        self.resizable(False, False)
        self.configure(fg_color=C["bg_dark"])
        self.grab_set()
        self.lift()
        self.focus_force()
        self.protocol("WM_DELETE_WINDOW", self._omitir_setup)

        self.update_idletasks()
        x = (self.winfo_screenwidth()  - self.ANCHO) // 2
        y = (self.winfo_screenheight() - self.ALTO)  // 2
        self.geometry(f"{self.ANCHO}x{self.ALTO}+{x}+{y}")

        self._build_ui()
        self._mostrar_paso(0)

    # ─── Layout ───────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Header
        hdr = ctk.CTkFrame(self, fg_color=C["sidebar"], corner_radius=0, height=82)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text="🅿  ParkingPro",
                     font=fuente(28, bold=True), text_color=C["blue"],
                     ).place(relx=0.5, rely=0.38, anchor="center")
        ctk.CTkLabel(hdr, text="Asistente de configuración inicial",
                     font=fuente(13), text_color=C["text_2"],
                     ).place(relx=0.5, rely=0.74, anchor="center")

        # Indicador de pasos
        self._frame_pasos = ctk.CTkFrame(self, fg_color=C["bg_dark"], height=54)
        self._frame_pasos.pack(fill="x", padx=50, pady=(18, 0))
        self._frame_pasos.pack_propagate(False)

        # Botones de navegación (fijados abajo)
        nav = ctk.CTkFrame(self, fg_color=C["bg_dark"], height=62)
        nav.pack(side="bottom", fill="x", padx=26, pady=(0, 18))
        nav.pack_propagate(False)

        # Contenido dinámico
        self._frame_contenido = ctk.CTkFrame(
            self, fg_color=C["bg_medium"], corner_radius=16,
        )
        self._frame_contenido.pack(side="top", fill="both", expand=True, padx=26, pady=(0, 14))

        self._btn_omitir = ctk.CTkButton(
            nav, text="Omitir configuración",
            fg_color="transparent", text_color=C["text_3"],
            hover_color=C["bg_light"], width=160,
            command=self._omitir_setup,
        )
        self._btn_omitir.pack(side="left", padx=4)

        self._btn_atras = ctk.CTkButton(
            nav, text="← Atrás",
            fg_color=C["bg_light"], hover_color=C["border"],
            text_color=C["text_1"], width=110,
            command=self._paso_anterior,
        )
        self._btn_atras.pack(side="left", padx=4)

        self._btn_siguiente = ctk.CTkButton(
            nav, text="Siguiente →",
            fg_color=C["blue"], hover_color=C["blue_h"],
            text_color="white", font=fuente(13, bold=True), width=170,
            command=self._paso_siguiente,
        )
        self._btn_siguiente.pack(side="right", padx=4)

    def _build_indicador(self):
        for w in self._frame_pasos.winfo_children():
            w.destroy()
        nombres = ["📋 Negocio", "🖨️ Impresora", "✅ Listo"]
        for i, nombre in enumerate(nombres):
            activo   = (i == self._paso_actual)
            completo = (i < self._paso_actual)
            ctk.CTkLabel(
                self._frame_pasos, text=nombre,
                font=fuente(11, bold=activo),
                text_color="white" if activo else (C["green"] if completo else C["text_3"]),
                fg_color=C["blue"] if activo else (C["green"] if completo else C["bg_light"]),
                corner_radius=20, width=148, height=34,
            ).grid(row=0, column=i * 2, padx=2)
            if i < len(nombres) - 1:
                ctk.CTkFrame(
                    self._frame_pasos,
                    fg_color=C["green"] if completo else C["border"],
                    width=40, height=2, corner_radius=0,
                ).grid(row=0, column=i * 2 + 1)

    # ─── Pasos ────────────────────────────────────────────────────────────────

    def _mostrar_paso(self, paso: int):
        self._paso_actual = paso
        self._build_indicador()
        for w in self._frame_contenido.winfo_children():
            w.destroy()

        {0: self._paso_negocio, 1: self._paso_impresora, 2: self._paso_listo}[paso]()

        self._btn_atras.configure(state="normal" if paso > 0 else "disabled")
        if paso == 2:
            self._btn_siguiente.configure(text="🚀  Comenzar a usar",
                                           command=self._finalizar)
        else:
            self._btn_siguiente.configure(text="Siguiente →",
                                           command=self._paso_siguiente)

    # ── Paso 0: Datos del negocio ──────────────────────────────────────────────

    def _paso_negocio(self):
        f = self._frame_contenido
        datos = self.config.get_datos_negocio()

        ctk.CTkLabel(f, text="Datos del Negocio",
                     font=fuente(18, bold=True), text_color=C["text_1"]).pack(pady=(22, 2))
        ctk.CTkLabel(f, text="Esta información aparecerá en los tickets impresos.",
                     font=fuente(12), text_color=C["text_2"]).pack(pady=(0, 18))

        self._entries_negocio = {}
        for label, key, valor in [
            ("Nombre del estacionamiento *", "nombre",    datos["nombre"]),
            ("Dirección",                    "direccion", datos["direccion"]),
            ("Teléfono",                     "telefono",  datos["telefono"]),
            ("RUC / N° Documento",           "ruc",       datos["ruc"]),
        ]:
            fila = ctk.CTkFrame(f, fg_color="transparent")
            fila.pack(fill="x", padx=36, pady=5)
            ctk.CTkLabel(fila, text=label, font=fuente(12), text_color=C["text_2"],
                         width=240, anchor="w").pack(side="left")
            entry = ctk.CTkEntry(fila, fg_color=C["bg_dark"], border_color=C["border"],
                                  text_color=C["text_1"], height=38, width=280)
            entry.insert(0, valor)
            entry.pack(side="right")
            self._entries_negocio[key] = entry

        # Moneda
        fila_m = ctk.CTkFrame(f, fg_color="transparent")
        fila_m.pack(fill="x", padx=36, pady=5)
        ctk.CTkLabel(fila_m, text="Símbolo de moneda", font=fuente(12),
                     text_color=C["text_2"], width=240, anchor="w").pack(side="left")
        self._entry_moneda = ctk.CTkEntry(fila_m, fg_color=C["bg_dark"],
                                           border_color=C["border"],
                                           text_color=C["text_1"], height=38, width=280)
        self._entry_moneda.insert(0, self.config.get_moneda())
        self._entry_moneda.pack(side="right")

    # ── Paso 1: Selección de ticketera ─────────────────────────────────────────
    #   Estructura:
    #     _frame_contenido
    #       └─ scroll_outer (CTkScrollableFrame — scroll general)
    #            ├─ título + descripción + label selección
    #            ├─ lista_border (frame con borde)
    #            │    └─ _setup_frame_lista (CTkScrollableFrame — scroll lista)
    #            ├─ label "Hardware sin driver"
    #            ├─ hw_border (frame con borde)
    #            │    └─ _setup_frame_hw (CTkScrollableFrame — scroll hardware)
    #            └─ _setup_log (TextBox)

    def _paso_impresora(self):
        f = self._frame_contenido

        # ── Scroll general (contenedor principal del paso) ────────────────────
        scroll_outer = ctk.CTkScrollableFrame(
            f, fg_color="transparent",
            scrollbar_fg_color=C["bg_light"],
        )
        scroll_outer.pack(fill="both", expand=True, padx=2, pady=2)

        # ── Encabezado ────────────────────────────────────────────────────────
        ctk.CTkLabel(
            scroll_outer, text="Selecciona tu Ticketera",
            font=fuente(18, bold=True), text_color=C["text_1"],
        ).pack(pady=(14, 2))

        ctk.CTkLabel(
            scroll_outer,
            text=(
                "Selecciona la impresora instalada que usarás.\n"
                "Las marcadas ⭐ tienen driver Generic/Text Only, ideal para térmicas.\n"
                "Las marcadas ⚠ tienen driver propio — usa 🔄 Cambiar Driver para ESC/POS."
            ),
            font=fuente(11), text_color=C["text_2"], justify="center",
        ).pack(pady=(0, 8))

        # ── Label de selección actual ─────────────────────────────────────────
        self._lbl_imp_sel = ctk.CTkLabel(
            scroll_outer,
            text="Ninguna impresora seleccionada",
            font=fuente(12, bold=True),
            text_color=C["text_3"],
        )
        self._lbl_imp_sel.pack(pady=(0, 8))

        # ── Sección: Lista de impresoras instaladas ───────────────────────────
        self._sec_label(scroll_outer, "Impresoras Instaladas en Windows")

        lista_border = ctk.CTkFrame(
            scroll_outer, fg_color=C["bg_dark"],
            corner_radius=10, border_color=C["border"], border_width=1,
        )
        lista_border.pack(fill="x", padx=10, pady=(0, 8))

        self._setup_frame_lista = ctk.CTkScrollableFrame(
            lista_border, fg_color="transparent", corner_radius=8,
            height=180,
        )
        self._setup_frame_lista.pack(fill="x", padx=2, pady=2)

        ctk.CTkLabel(
            self._setup_frame_lista, text="🔄  Buscando impresoras...",
            font=fuente(12), text_color=C["yellow"],
        ).pack(pady=20)

        # ── Sección: Hardware sin driver ──────────────────────────────────────
        self._sec_label(
            scroll_outer,
            "Hardware USB sin Driver  (instala para poder seleccionarlo)",
        )

        hw_border = ctk.CTkFrame(
            scroll_outer, fg_color=C["bg_dark"],
            corner_radius=10, border_color=C["border"], border_width=1,
        )
        hw_border.pack(fill="x", padx=10, pady=(0, 8))

        self._setup_frame_hw = ctk.CTkScrollableFrame(
            hw_border, fg_color="transparent", corner_radius=8,
            height=90,
        )
        self._setup_frame_hw.pack(fill="x", padx=2, pady=2)

        ctk.CTkLabel(
            self._setup_frame_hw, text="Escaneando hardware USB...",
            font=fuente(10), text_color=C["text_3"],
        ).pack(pady=10)

        # ── Log mini ─────────────────────────────────────────────────────────
        self._sec_label(scroll_outer, "Registro de actividad")

        self._setup_log = ctk.CTkTextbox(
            scroll_outer, fg_color=C["bg_dark"], text_color=C["text_3"],
            height=52, font=ctk.CTkFont("Courier", 10),
        )
        self._setup_log.pack(fill="x", padx=10, pady=(0, 10))
        self._setup_log.configure(state="disabled")

        # Escanear en background
        threading.Thread(target=self._scan_setup, daemon=True).start()

    # ── Helper de sección ────────────────────────────────────────────────────

    def _sec_label(self, parent, titulo: str):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.pack(fill="x", padx=10, pady=(8, 4))
        ctk.CTkLabel(f, text=titulo, font=fuente(11, bold=True),
                     text_color=C["text_3"], anchor="w").pack(side="left")
        ctk.CTkFrame(f, fg_color=C["border"], height=1).pack(
            side="left", fill="x", expand=True, padx=(8, 0), pady=6)

    # ── Escaneo ───────────────────────────────────────────────────────────────

    def _scan_setup(self):
        inst = PrinterInstaller()
        impresoras = inst.listar_impresoras_detalle()
        hardware   = inst.listar_hardware_sin_driver()
        self.after(0, lambda: self._mostrar_setup_resultados(impresoras, hardware))

    def _mostrar_setup_resultados(self, impresoras: List[Dict], hardware: List[Dict]):
        if not self.winfo_exists():
            return

        # Lista de impresoras
        for w in self._setup_frame_lista.winfo_children():
            w.destroy()

        if not impresoras:
            ctk.CTkLabel(
                self._setup_frame_lista,
                text=(
                    "❌  No se encontraron impresoras instaladas.\n"
                    "Instala tu ticketera en Windows primero o\n"
                    "usa el botón de instalación de driver más abajo."
                ),
                font=fuente(11), text_color=C["red"],
            ).pack(pady=20)
        else:
            for imp in impresoras:
                self._render_setup_card(imp)

        self._setup_log_append(
            f"Encontradas: {len(impresoras)} impresora(s) • {len(hardware)} sin driver")

        # Hardware sin driver
        for w in self._setup_frame_hw.winfo_children():
            w.destroy()

        if not hardware:
            ctk.CTkLabel(
                self._setup_frame_hw,
                text="✓ Sin hardware pendiente de driver",
                font=fuente(10), text_color=C["text_3"],
            ).pack(pady=10)
        else:
            for dev in hardware:
                self._render_setup_hw_card(dev)

    def _render_setup_card(self, imp: Dict):
        nombre    = imp["nombre"]
        driver    = imp["driver"]
        es_compat = imp["es_compatible_termica"]
        es_ticket = imp.get("es_ticketera", False)
        es_activa = (nombre == self._imp_seleccionada)

        border_c = C["green"] if es_activa else (C["blue"] if es_compat else C["border"])
        border_w = 2 if (es_activa or es_compat) else 1
        bg_c     = C["bg_medium"] if es_compat else C["bg_dark"]

        card = ctk.CTkFrame(self._setup_frame_lista, fg_color=bg_c, corner_radius=8,
                             border_color=border_c, border_width=border_w)
        card.pack(fill="x", padx=6, pady=3)

        # Izquierda: info
        left = ctk.CTkFrame(card, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True, padx=12, pady=8)

        top = ctk.CTkFrame(left, fg_color="transparent")
        top.pack(fill="x")

        ctk.CTkLabel(top, text=f"🖨️  {nombre}",
                     font=fuente(12, bold=True),
                     text_color=C["green"] if es_activa else C["text_1"],
                     anchor="w").pack(side="left")

        if es_compat:
            ctk.CTkLabel(top, text="⭐ Recomendada",
                          font=fuente(9), fg_color=C["blue"],
                          text_color="white", corner_radius=6,
                          width=90, height=18).pack(side="left", padx=8)
        elif es_ticket:
            ctk.CTkLabel(top, text="⚠ Driver propio",
                          font=fuente(9), fg_color=C["yellow_h"],
                          text_color="white", corner_radius=6,
                          width=90, height=18).pack(side="left", padx=8)

        ctk.CTkLabel(left, text=f"Driver: {driver[:52]}",
                     font=fuente(10), text_color=C["text_3"],
                     anchor="w").pack(fill="x")

        # Derecha: botones
        right = ctk.CTkFrame(card, fg_color="transparent")
        right.pack(side="right", padx=12, pady=8)

        if es_activa:
            ctk.CTkLabel(right, text="✓ Seleccionada",
                         font=fuente(11, bold=True), text_color=C["green"]).pack()
        else:
            btn_c = C["blue"] if es_compat else C["bg_light"]
            btn_h = C["blue_h"] if es_compat else C["border"]
            ctk.CTkButton(
                right, text="Seleccionar",
                fg_color=btn_c, hover_color=btn_h,
                text_color="white", font=fuente(11, bold=True),
                width=100, height=30, corner_radius=8,
                command=lambda n=nombre: self._seleccionar_imp_setup(n),
            ).pack()

            # Botón "Cambiar Driver" para ticketeras con driver propio (no-Generic)
            if not es_compat and es_ticket:
                ctk.CTkButton(
                    right, text="🔄 Cambiar Driver",
                    fg_color="#7c2d12", hover_color="#9a3412",
                    text_color="white", font=fuente(10, bold=True),
                    width=120, height=26, corner_radius=8,
                    command=lambda n=nombre: self._cambiar_driver_setup(n),
                ).pack(pady=(4, 0))

    def _render_setup_hw_card(self, dev: Dict):
        nombre = dev.get("nombre", "Desconocido")
        card = ctk.CTkFrame(self._setup_frame_hw, fg_color=C["bg_medium"],
                             corner_radius=6, border_color=C["yellow"], border_width=1)
        card.pack(fill="x", padx=6, pady=2)

        left = ctk.CTkFrame(card, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True, padx=12, pady=6)

        ctk.CTkLabel(left, text=f"🖨️  {nombre}",
                     font=fuente(11, bold=True), text_color=C["yellow"],
                     anchor="w").pack(fill="x")
        ctk.CTkLabel(left, text="Sin driver — necesita instalación",
                     font=fuente(10), text_color=C["text_3"],
                     anchor="w").pack(fill="x")

        ctk.CTkButton(
            card, text="🛡️ Instalar\n(Admin)",
            fg_color="#ea580c", hover_color="#c2410c",
            text_color="white", font=fuente(10, bold=True),
            width=110, height=40,
            command=lambda n=nombre: self._instalar_driver_setup(n),
        ).pack(side="right", padx=10, pady=6)

    # ── Acciones sobre impresoras ─────────────────────────────────────────────

    def _seleccionar_imp_setup(self, nombre: str):
        self._imp_seleccionada = nombre
        self._lbl_imp_sel.configure(
            text=f"✓ Seleccionada: {nombre}", text_color=C["green"])
        self._setup_log_append(f"✅ Impresora seleccionada: {nombre}")
        # Re-renderizar para actualizar badges
        threading.Thread(target=self._scan_setup, daemon=True).start()

    def _cambiar_driver_setup(self, nombre_impresora: str):
        """
        Cambia el driver de una impresora a Generic / Text Only (necesita Admin).
        Igual que la opción equivalente en el panel de Configuración.
        """
        if not messagebox.askyesno(
            "Cambiar Driver a Generic/Text Only",
            f"Se cambiará el driver de:\n\n  {nombre_impresora}\n\n"
            "al driver  Generic / Text Only  (ideal para ESC/POS térmico).\n\n"
            "Windows pedirá permisos de Administrador.\n"
            "⚠ Si el driver propio tiene funciones especiales, se perderán.\n\n"
            "¿Continuar?",
        ):
            return

        self._setup_log_append(f"Iniciando cambio de driver para: {nombre_impresora}...")

        def _run():
            inst = PrinterInstaller(nombre_impresora)
            exito = inst.cambiar_driver_generico(
                nombre_impresora,
                log=lambda m: self.after(0, self._setup_log_append, m),
            )

            def _ui():
                if not self.winfo_exists():
                    return
                if exito:
                    self._setup_log_append(
                        f"✅ Driver cambiado. Ahora puedes seleccionarla.")
                    self._seleccionar_imp_setup(nombre_impresora)
                else:
                    self._setup_log_append("❌ No se pudo cambiar el driver.")

            self.after(0, _ui)

        threading.Thread(target=_run, daemon=True).start()

    def _instalar_driver_setup(self, nombre_modelo: str):
        self._setup_log_append(f"Instalando driver para: {nombre_modelo}...")

        def _run():
            inst  = PrinterInstaller(nombre_modelo)
            exito = inst.instalar_como_admin(
                nombre_modelo,
                log=lambda m: self.after(0, self._setup_log_append, m),
            )

            def _ui():
                if not self.winfo_exists():
                    return
                if exito:
                    self._seleccionar_imp_setup(nombre_modelo)
                else:
                    self._setup_log_append("❌ Instalación fallida. Intenta manualmente.")

            self.after(0, _ui)

        threading.Thread(target=_run, daemon=True).start()

    def _setup_log_append(self, texto: str):
        try:
            self._setup_log.configure(state="normal")
            self._setup_log.insert("end", texto + "\n")
            self._setup_log.see("end")
            self._setup_log.configure(state="disabled")
        except Exception:
            pass

    # ── Paso 2: Listo ─────────────────────────────────────────────────────────

    def _paso_listo(self):
        f = self._frame_contenido
        ctk.CTkLabel(f, text="🎉", font=ctk.CTkFont(size=58)).pack(pady=(30, 6))
        ctk.CTkLabel(f, text="¡Todo listo para comenzar!",
                     font=fuente(22, bold=True), text_color=C["green"]).pack()
        ctk.CTkLabel(
            f,
            text=(
                "ParkingPro está configurado y listo para usar.\n"
                "Puedes ajustar tarifas y configuración en cualquier\n"
                "momento desde el menú  ⚙️ Configuración."
            ),
            font=fuente(13), text_color=C["text_2"], justify="center",
        ).pack(pady=16)

        datos = self.config.get_datos_negocio()
        if self._imp_seleccionada:
            imp_texto = self._imp_seleccionada
        else:
            imp_texto = "(Ninguna — configura en ⚙️ Ajustes)"

        resumen = (
            f"🏢  Negocio:    {datos['nombre']}\n"
            f"🖨️  Impresora: {imp_texto}\n"
            f"💵  Moneda:    {self.config.get_moneda()}"
        )
        card = ctk.CTkFrame(f, fg_color=C["bg_dark"], corner_radius=12)
        card.pack(padx=60, pady=8, fill="x")
        ctk.CTkLabel(card, text=resumen, font=fuente(12),
                     text_color=C["text_2"], justify="left").pack(padx=20, pady=14)

    # ─── Navegación ───────────────────────────────────────────────────────────

    def _guardar_paso_actual(self):
        if self._paso_actual == 0:
            e = self._entries_negocio
            if not e:
                return
            self.config.set_datos_negocio(
                e["nombre"].get().strip() or "Mi Estacionamiento",
                e["direccion"].get().strip(),
                e["telefono"].get().strip(),
                e["ruc"].get().strip(),
            )
            moneda = self._entry_moneda.get().strip()
            if moneda:
                self.config.set("sistema", "moneda", moneda)

        elif self._paso_actual == 1:
            # Solo guardar si el usuario eligió una impresora
            if self._imp_seleccionada:
                self.config.set("impresora", "nombre", self._imp_seleccionada)

    def _paso_siguiente(self):
        self._guardar_paso_actual()
        if self._paso_actual < 2:
            self._mostrar_paso(self._paso_actual + 1)

    def _paso_anterior(self):
        if self._paso_actual > 0:
            self._mostrar_paso(self._paso_actual - 1)

    def _finalizar(self):
        self._guardar_paso_actual()
        self.config.marcar_configurado()
        self.destroy()
        if self.callback:
            self.callback()

    def _omitir_setup(self):
        self.config.marcar_configurado()
        self.destroy()
        if self.callback:
            self.callback()