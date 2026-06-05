"""
ParkingPro - Asistente de primera configuración
Pasos: Datos del negocio → Selección de ticketera → Listo
"""
import threading
import customtkinter as ctk
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
        self._imp_seleccionada: Optional[str] = config.get_nombre_impresora()

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

        # Botones de navegación (fijados abajo primero)
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
        self._entry_moneda = ctk.CTkEntry(fila_m, fg_color=C["bg_dark"], border_color=C["border"],
                                           text_color=C["text_1"], height=38, width=280)
        self._entry_moneda.insert(0, self.config.get_moneda())
        self._entry_moneda.pack(side="right")

    # ── Paso 1: Selección de ticketera ─────────────────────────────────────────

    def _paso_impresora(self):
        f = self._frame_contenido

        ctk.CTkLabel(f, text="Selecciona tu Ticketera",
                     font=fuente(18, bold=True), text_color=C["text_1"]).pack(pady=(18, 2))
        ctk.CTkLabel(
            f,
            text="Selecciona la impresora instalada que usarás.\n"
                 "Las marcadas ⭐ tienen driver Generic/Text Only, ideal para térmicas.",
            font=fuente(12), text_color=C["text_2"], justify="center",
        ).pack(pady=(0, 12))

        # Label de selección actual
        self._lbl_imp_sel = ctk.CTkLabel(
            f,
            text=f"Seleccionada: {self._imp_seleccionada or '(ninguna)'}",
            font=fuente(12, bold=True),
            text_color=C["green"] if self._imp_seleccionada else C["text_3"],
        )
        self._lbl_imp_sel.pack(pady=(0, 8))

        # Frame lista (scrollable)
        self._setup_frame_lista = ctk.CTkScrollableFrame(
            f, fg_color=C["bg_dark"], corner_radius=10, height=220,
        )
        self._setup_frame_lista.pack(fill="x", padx=24, pady=(0, 8))

        ctk.CTkLabel(self._setup_frame_lista, text="🔄  Buscando impresoras...",
                     font=fuente(12), text_color=C["yellow"]).pack(pady=24)

        # Sección hardware sin driver
        ctk.CTkLabel(f, text="Hardware sin Driver (instala para poder seleccionarlo):",
                     font=fuente(10, bold=True), text_color=C["text_3"],
                     anchor="w").pack(fill="x", padx=24, pady=(4, 2))

        self._setup_frame_hw = ctk.CTkFrame(f, fg_color=C["bg_dark"], corner_radius=8)
        self._setup_frame_hw.pack(fill="x", padx=24, pady=(0, 6))
        ctk.CTkLabel(self._setup_frame_hw, text="Escaneando...",
                     font=fuente(10), text_color=C["text_3"]).pack(pady=8)

        # Log mini
        self._setup_log = ctk.CTkTextbox(
            f, fg_color=C["bg_dark"], text_color=C["text_3"],
            height=36, font=ctk.CTkFont("Courier", 10),
        )
        self._setup_log.pack(fill="x", padx=24, pady=(0, 6))

        # Escanear
        threading.Thread(target=self._scan_setup, daemon=True).start()

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
                text="❌  No se encontraron impresoras instaladas.\n"
                     "Instala tu ticketera en Windows primero o\n"
                     "usa el botón de instalación de driver más abajo.",
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
            ctk.CTkLabel(self._setup_frame_hw,
                         text="✓ Sin hardware pendiente de driver",
                         font=fuente(10), text_color=C["text_3"]).pack(pady=8)
        else:
            for dev in hardware:
                self._render_setup_hw_card(dev)

    def _render_setup_card(self, imp: Dict):
        nombre    = imp["nombre"]
        driver    = imp["driver"]
        es_compat = imp["es_compatible_termica"]
        es_activa = (nombre == self._imp_seleccionada)

        border_c = C["green"] if es_activa else (C["blue"] if es_compat else C["border"])
        border_w = 2 if (es_activa or es_compat) else 1
        bg_c     = C["bg_medium"] if es_compat else C["bg_dark"]

        card = ctk.CTkFrame(self._setup_frame_lista, fg_color=bg_c, corner_radius=8,
                             border_color=border_c, border_width=border_w)
        card.pack(fill="x", padx=6, pady=3)

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

        ctk.CTkLabel(left, text=f"Driver: {driver[:50]}",
                     font=fuente(10), text_color=C["text_3"],
                     anchor="w").pack(fill="x")

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

    def _render_setup_hw_card(self, dev: Dict):
        nombre = dev.get("nombre", "Desconocido")
        card = ctk.CTkFrame(self._setup_frame_hw, fg_color=C["bg_medium"],
                             corner_radius=6, border_color=C["yellow"], border_width=1)
        card.pack(fill="x", padx=6, pady=2)

        ctk.CTkLabel(card, text=f"⚡ {nombre} — sin driver",
                     font=fuente(11), text_color=C["yellow"],
                     anchor="w").pack(side="left", padx=12, pady=6)

        ctk.CTkButton(
            card, text="🛡️ Instalar (Admin)",
            fg_color="#ea580c", hover_color="#c2410c",
            text_color="white", font=fuente(10, bold=True),
            width=140, height=28,
            command=lambda n=nombre: self._instalar_driver_setup(n),
        ).pack(side="right", padx=10, pady=6)

    def _seleccionar_imp_setup(self, nombre: str):
        self._imp_seleccionada = nombre
        self._lbl_imp_sel.configure(
            text=f"✓ Seleccionada: {nombre}", text_color=C["green"])
        self._setup_log_append(f"✅ Impresora seleccionada: {nombre}")
        # Re-renderizar para actualizar badges
        threading.Thread(target=self._scan_setup, daemon=True).start()

    def _instalar_driver_setup(self, nombre_modelo: str):
        self._setup_log_append(f"Instalando driver para: {nombre_modelo}...")

        def _run():
            inst = PrinterInstaller(nombre_modelo)
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
        imp   = self._imp_seleccionada or self.config.get_nombre_impresora()
        resumen = (
            f"🏢  Negocio:    {datos['nombre']}\n"
            f"🖨️  Impresora: {imp}\n"
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