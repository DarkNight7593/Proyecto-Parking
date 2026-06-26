"""
ParkingPro - Panel de Configuración
Tabs: Negocio | Tarifas | Impresora

El estado de la impresora lo provee main.py (que ya corre su loop cada 5 s).
Este panel no hace su propia consulta WMIC; en cambio:
  • Recibe 'get_estado_imp' (callable) para leer el último estado conocido al abrirse.
  • Recibe el estado actualizado vía actualizar_estado_imp() cada vez que main lo llama.
"""
import threading
import customtkinter as ctk
from tkinter import messagebox
from typing import Dict, List, Callable, Optional

from ui.theme import C, fuente, TIPOS_VEHICULO
from installer import PrinterInstaller

# Máximo de líneas que se conservan visibles en el log de actividad.
# Evita que el CTkTextbox crezca sin límite y ralentice la UI.
_LOG_MAX_LINEAS = 200


class PanelConfiguracion(ctk.CTkFrame):
    """
    Panel de configuración con tres pestañas:
      • Negocio   — datos del negocio y moneda
      • Tarifas   — precio/hora por tipo de vehículo + minutos de gracia
      • Impresora — selección de ticketera desde lista instalada en Windows
    """

    def __init__(
        self,
        parent,
        config,
        db,
        printer,
        on_guardado: Callable = None,
        get_estado_imp: Callable = None,   # () → dict con 'nivel' y 'mensaje'
        **kwargs,
    ):
        super().__init__(parent, fg_color=C["bg_dark"], corner_radius=0, **kwargs)
        self.config      = config
        self.db          = db
        self.printer     = printer
        self.on_guardado = on_guardado

        # Getter que devuelve el último estado calculado por main (sin llamar a WMIC).
        self._get_estado_imp: Optional[Callable] = get_estado_imp

        # BUG FIX: contador de escaneo para descartar resultados de hilos obsoletos.
        # Si el usuario pulsa "Actualizar" varias veces seguidas, solo el último
        # hilo activo actualiza la UI; los anteriores se ignoran silenciosamente.
        self._scan_id: int = 0

        self._build_ui()

    def set_printer(self, printer):
        self.printer = printer

    # ─── API pública: main llama aquí cuando cambia el estado de la impresora ─

    def actualizar_estado_imp(self, estado: dict):
        """
        Invocado por main._apply_printer_status cada vez que cambia el estado.
        Actualiza el badge de la pestaña Impresora si el widget todavía existe.
        Debe llamarse siempre desde el hilo principal (p.ej. via self.after(0, ...)).
        """
        if self.winfo_exists():
            self._actualizar_estado_badge(estado)

    # ─── Layout principal ─────────────────────────────────────────────────────

    def _build_ui(self):
        hdr = ctk.CTkFrame(self, fg_color=C["sidebar"], height=56, corner_radius=0)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        ctk.CTkLabel(
            hdr, text="⚙️  Configuración del Sistema",
            font=fuente(17, bold=True), text_color=C["text_1"],
        ).pack(side="left", padx=24)

        self._tabs = ctk.CTkTabview(
            self,
            fg_color=C["bg_medium"],
            segmented_button_fg_color=C["bg_dark"],
            segmented_button_selected_color=C["blue"],
            segmented_button_selected_hover_color=C["blue_h"],
            segmented_button_unselected_color=C["bg_dark"],
            segmented_button_unselected_hover_color=C["bg_light"],
            text_color=C["text_1"],
            corner_radius=14,
        )
        self._tabs.pack(fill="both", expand=True, padx=20, pady=12)

        for tab in ("🏢  Negocio", "💰  Tarifas", "🖨️  Impresora"):
            self._tabs.add(tab)

        self._build_tab_negocio(self._tabs.tab("🏢  Negocio"))
        self._build_tab_tarifas(self._tabs.tab("💰  Tarifas"))
        self._build_tab_impresora(self._tabs.tab("🖨️  Impresora"))

    # ─── Tab: Negocio ─────────────────────────────────────────────────────────

    def _build_tab_negocio(self, parent):
        scroll = ctk.CTkScrollableFrame(
            parent, fg_color="transparent", scrollbar_fg_color=C["bg_light"])
        scroll.pack(fill="both", expand=True, padx=4, pady=4)

        self._entries_negocio: Dict[str, ctk.CTkEntry] = {}

        self._seccion(scroll, "Datos del Negocio")
        datos = self.config.get_datos_negocio()
        for label, key, valor in [
            ("Nombre del estacionamiento", "nombre",    datos["nombre"]),
            ("Dirección",                  "direccion", datos["direccion"]),
            ("Teléfono",                   "telefono",  datos["telefono"]),
            ("RUC / N° Documento",         "ruc",       datos["ruc"]),
        ]:
            self._entries_negocio[key] = self._campo_entrada(scroll, label, valor)

        self._seccion(scroll, "Sistema")
        self._entry_moneda = self._campo_entrada(
            scroll, "Símbolo de moneda (ej: S/, $, €)", self.config.get_moneda())

        ctk.CTkButton(
            scroll, text="💾  Guardar Datos del Negocio",
            fg_color=C["blue"], hover_color=C["blue_h"],
            text_color="white", font=fuente(13, bold=True),
            height=42, command=self._guardar_negocio,
        ).pack(pady=(20, 6))

    def _guardar_negocio(self):
        e = self._entries_negocio
        self.config.set_datos_negocio(
            e["nombre"].get().strip() or "Mi Estacionamiento",
            e["direccion"].get().strip(),
            e["telefono"].get().strip(),
            e["ruc"].get().strip(),
        )
        moneda = self._entry_moneda.get().strip()
        if moneda:
            self.config.set("sistema", "moneda", moneda)

        messagebox.showinfo("✅ Guardado", "Datos del negocio guardados correctamente.")

        if self.on_guardado:
            self.on_guardado()

    # ─── Tab: Tarifas — validación de entrada en tiempo real ──────────────────

    @staticmethod
    def _crear_var_tarifa(valor_inicial: float) -> ctk.StringVar:
        """
        Devuelve un StringVar con validación automática vía trace.

        Solo acepta números con el formato: [0-999][.][00]
          • Máximo 3 dígitos enteros   (ej: 1, 12, 999)
          • Punto decimal opcional
          • Máximo 2 dígitos decimales (ej: .5, .50)
          • Ejemplos válidos: 5  |  12.5  |  999.99
          • Ejemplos inválidos: 1000  |  1.234  |  abc

        El trace revierte automáticamente cualquier carácter ilegal
        sin necesitar botón de validar — la UI no congela porque todo
        sucede en el hilo principal de Tkinter.
        """
        texto_inicial = f"{valor_inicial:.2f}"
        var = ctk.StringVar(value=texto_inicial)
        # Usamos un dict mutable como "celda por referencia" para la closure.
        estado = {"anterior": texto_inicial, "revirtiendo": False}

        def _on_write(*_):
            # Guardián de recursión: set() dentro del trace vuelve a dispararlo.
            if estado["revirtiendo"]:
                return

            texto = var.get()
            partes = texto.split(".")

            if len(partes) == 1:
                # Sin punto decimal: solo dígitos, máximo 3 caracteres.
                valido = (partes[0] == "" or partes[0].isdigit()) and len(partes[0]) <= 3
            elif len(partes) == 2:
                # Con punto decimal: entero ≤3 dígitos, fracción ≤2 dígitos.
                valido = (
                    (partes[0] == "" or partes[0].isdigit()) and len(partes[0]) <= 3
                    and (partes[1] == "" or partes[1].isdigit()) and len(partes[1]) <= 2
                )
            else:
                # Más de un punto decimal → inválido.
                valido = False

            if valido:
                estado["anterior"] = texto
            else:
                # Revertir al valor previo válido.
                estado["revirtiendo"] = True
                var.set(estado["anterior"])
                estado["revirtiendo"] = False

        var.trace_add("write", _on_write)
        return var

    @staticmethod
    def _crear_var_minutos(valor_inicial: int) -> ctk.StringVar:
        """
        Devuelve un StringVar con validación automática vía trace.

        Solo acepta enteros de hasta 2 dígitos (0 – 99).
        Letras, puntos decimales o más de 2 dígitos son rechazados
        en tiempo real sin congelar la UI.
        """
        texto_inicial = str(max(0, valor_inicial))
        var = ctk.StringVar(value=texto_inicial)
        estado = {"anterior": texto_inicial, "revirtiendo": False}

        def _on_write(*_):
            if estado["revirtiendo"]:
                return
            texto = var.get()
            # Solo dígitos, máximo 2 caracteres.
            valido = (texto == "" or texto.isdigit()) and len(texto) <= 2
            if valido:
                estado["anterior"] = texto
            else:
                estado["revirtiendo"] = True
                var.set(estado["anterior"])
                estado["revirtiendo"] = False

        var.trace_add("write", _on_write)
        return var

    def _build_tab_tarifas(self, parent):
        scroll = ctk.CTkScrollableFrame(
            parent, fg_color="transparent", scrollbar_fg_color=C["bg_light"])
        scroll.pack(fill="both", expand=True, padx=4, pady=4)

        self._seccion(scroll, "Precio por Hora — por Tipo de Vehículo")
        ctk.CTkLabel(
            scroll,
            text="Tarifa que se cobra por cada hora de estacionamiento.",
            font=fuente(11), text_color=C["text_3"],
        ).pack(anchor="w", padx=10, pady=(0, 12))

        self._entries_tarifas: Dict[str, ctk.CTkEntry] = {}
        # BUG FIX: guardamos referencias a los StringVar para que el garbage
        # collector no los destruya mientras el panel esté abierto.
        self._vars_tarifas: Dict[str, ctk.StringVar] = {}

        tarifas = self.config.get_all_tarifas()

        grid = ctk.CTkFrame(scroll, fg_color="transparent")
        grid.pack(fill="x", padx=4)
        for i, tipo in enumerate(TIPOS_VEHICULO):
            fila, col = divmod(i, 2)
            card = self._tarifa_card(grid, tipo, tarifas.get(tipo["key"], 2.0))
            card.grid(row=fila, column=col, padx=8, pady=6, sticky="ew")
            grid.grid_columnconfigure(col, weight=1)

        self._seccion(scroll, "Tolerancia / Tiempo Libre")
        fila_tl = ctk.CTkFrame(scroll, fg_color=C["bg_dark"], corner_radius=10)
        fila_tl.pack(fill="x", padx=4, pady=4)
        ctk.CTkLabel(
            fila_tl, text="Minutos de gracia antes de empezar a cobrar:",
            font=fuente(12), text_color=C["text_2"],
        ).pack(side="left", padx=16, pady=14)

        # StringVar validado: solo entero de 0 a 99 (máximo 2 dígitos).
        self._var_tl = self._crear_var_minutos(self.config.get_tiempo_libre())
        self._entry_tl_tarifas = ctk.CTkEntry(
            fila_tl,
            textvariable=self._var_tl,
            fg_color=C["bg_medium"], border_color=C["border"],
            text_color=C["text_1"], height=36, width=80, justify="center",
        )
        self._entry_tl_tarifas.pack(side="right", padx=16, pady=14)

        ctk.CTkButton(
            scroll, text="💾  Guardar Tarifas",
            fg_color=C["green"], hover_color=C["green_h"],
            text_color="white", font=fuente(13, bold=True),
            height=42, command=self._guardar_tarifas,
        ).pack(pady=(20, 6))

    def _tarifa_card(self, parent, tipo: Dict, tarifa_actual: float) -> ctk.CTkFrame:
        """Construye la tarjeta de precio para un tipo de vehículo."""
        card = ctk.CTkFrame(parent, fg_color=C["bg_dark"], corner_radius=14)
        ctk.CTkFrame(card, fg_color=tipo["color"], height=4, corner_radius=0).pack(fill="x")

        cuerpo = ctk.CTkFrame(card, fg_color="transparent")
        cuerpo.pack(fill="x", padx=14, pady=10)
        ctk.CTkLabel(
            cuerpo, text=f"{tipo['emoji']}  {tipo['nombre']}",
            font=fuente(14, bold=True), text_color=tipo["color"], anchor="w",
        ).pack(fill="x")

        fila_precio = ctk.CTkFrame(cuerpo, fg_color="transparent")
        fila_precio.pack(fill="x", pady=(6, 0))
        ctk.CTkLabel(
            fila_precio, text=self.config.get_moneda(),
            font=fuente(13), text_color=C["text_2"],
        ).pack(side="left")

        # StringVar con validación en tiempo real: máx 3 dígitos enteros + 2 decimales.
        var = self._crear_var_tarifa(tarifa_actual)
        # Guardar referencia en el dict para evitar recolección por GC.
        self._vars_tarifas[tipo["key"]] = var

        entry = ctk.CTkEntry(
            fila_precio,
            textvariable=var,
            fg_color=C["bg_medium"], border_color=tipo["color"], border_width=1,
            text_color=tipo["color"], font=fuente(16, bold=True),
            height=36, width=90, justify="center",
        )
        entry.pack(side="left", padx=4)
        ctk.CTkLabel(
            fila_precio, text="/ hr",
            font=fuente(11), text_color=C["text_3"],
        ).pack(side="left")

        self._entries_tarifas[tipo["key"]] = entry
        return card

    def _guardar_tarifas(self):
        """Valida y persiste todas las tarifas y los minutos de gracia."""
        errores = []

        for key, entry in self._entries_tarifas.items():
            tipo = next((t for t in TIPOS_VEHICULO if t["key"] == key), None)
            color_orig = tipo["color"] if tipo else C["border"]
            try:
                val = float(entry.get().strip().replace(",", "."))
                if val < 0:
                    raise ValueError
                self.config.set_tarifa(key, val)
                entry.configure(border_color=color_orig)
            except ValueError:
                errores.append(key)
                entry.configure(border_color=C["red"])

        try:
            # BUG FIX: si el campo está vacío (usuario borró todo), lo tratamos como 0
            # en lugar de lanzar ValueError y marcarlo en rojo.
            texto_tl = self._entry_tl_tarifas.get().strip()
            val_tl = max(0, int(texto_tl)) if texto_tl else 0
            self.config.set("sistema", "tiempo_libre_min", str(val_tl))
            self._entry_tl_tarifas.configure(border_color=C["border"])
        except ValueError:
            errores.append("Tiempo libre")
            self._entry_tl_tarifas.configure(border_color=C["red"])

        if errores:
            messagebox.showwarning(
                "Advertencia",
                f"Valores inválidos en: {', '.join(errores)}\n"
                "Los demás se guardaron correctamente.",
            )
        else:
            messagebox.showinfo("✅ Guardado", "Tarifas guardadas correctamente.")

        if self.on_guardado:
            self.on_guardado()

    # ─── Tab: Impresora ───────────────────────────────────────────────────────

    def _build_tab_impresora(self, parent):
        self._imp_seleccionada: str = self.config.get_nombre_impresora()

        # Botones de acción fijos en la parte inferior.
        # Se empaquetan ANTES que el scroll para que queden anclados abajo.
        btns_frame = ctk.CTkFrame(parent, fg_color=C["bg_dark"], corner_radius=0)
        btns_frame.pack(side="bottom", fill="x", padx=4, pady=(4, 6))

        btns_inner = ctk.CTkFrame(btns_frame, fg_color="transparent")
        btns_inner.pack(pady=6)

        ctk.CTkButton(
            btns_inner, text="🔄  Actualizar Lista",
            fg_color=C["bg_light"], hover_color=C["border"],
            text_color=C["text_1"], font=fuente(12), height=40, width=180,
            command=self._escanear,
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            btns_inner, text="🧪  Página de Prueba",
            fg_color=C["bg_dark"], hover_color=C["bg_light"],
            text_color=C["text_2"], font=fuente(12), height=40, width=160,
            border_color=C["border"], border_width=1,
            command=self._test_impresora,
        ).pack(side="left", padx=5)

        # Contenido scrollable principal
        scroll = ctk.CTkScrollableFrame(
            parent, fg_color="transparent", scrollbar_fg_color=C["bg_light"])
        scroll.pack(fill="both", expand=True, padx=4, pady=4)

        # ── Ticketera activa ──────────────────────────────────────────────────
        self._seccion(scroll, "Ticketera Activa")

        self._card_activa = ctk.CTkFrame(
            scroll, fg_color=C["bg_dark"], corner_radius=10,
            border_color=C["green"], border_width=2)
        self._card_activa.pack(fill="x", padx=4, pady=(0, 4))

        fila_act = ctk.CTkFrame(self._card_activa, fg_color="transparent")
        fila_act.pack(fill="x", padx=12, pady=(8, 0))

        # Muestra "No seleccionada" si el valor es vacío o el placeholder de fábrica.
        nombre_mostrar = (
            self._imp_seleccionada
            if self._imp_seleccionada and self._imp_seleccionada != "TicketeraEstacionamiento"
            else "Ninguna (No seleccionada)"
        )

        self._lbl_imp_activa = ctk.CTkLabel(
            fila_act,
            text=f"🖨️  {nombre_mostrar}",
            font=fuente(14, bold=True), text_color=C["green"], anchor="w",
        )
        self._lbl_imp_activa.pack(side="left", fill="x", expand=True)

        # Botón de reparación: se muestra/oculta dinámicamente según el estado.
        self._btn_reparar = ctk.CTkButton(
            fila_act, text="🔧 Reparar USB",
            fg_color="#ea580c", hover_color="#c2410c",
            text_color="white", font=fuente(11, bold=True), height=26, width=100,
            command=self._reparar_impresora,
        )
        # El pack de este botón lo gestiona _actualizar_estado_badge.

        self._lbl_estado_imp = ctk.CTkLabel(
            self._card_activa, text="Verificando estado...",
            font=fuente(11), text_color=C["text_3"],
        )
        self._lbl_estado_imp.pack(anchor="w", padx=12, pady=(2, 8))

        # ── Lista de impresoras instaladas en Windows ─────────────────────────
        self._seccion(scroll, "Impresoras Instaladas en Windows")

        ctk.CTkLabel(
            scroll,
            text=(
                "Selecciona la impresora que usarás como ticketera.\n"
                "⭐ = driver Generic/Text Only (ideal ESC/POS)  •  "
                "🔄 = cambiar driver a Generic (requiere Admin)"
            ),
            font=fuente(11), text_color=C["text_3"], justify="left",
        ).pack(anchor="w", padx=10, pady=(0, 6))

        lista_border = ctk.CTkFrame(
            scroll, fg_color=C["bg_dark"],
            corner_radius=12, border_color=C["border"], border_width=1)
        lista_border.pack(fill="x", padx=4, pady=(0, 8))

        self._frame_lista = ctk.CTkScrollableFrame(
            lista_border, fg_color="transparent", corner_radius=10, height=200)
        self._frame_lista.pack(fill="x", padx=2, pady=2)
        ctk.CTkLabel(
            self._frame_lista, text="🔄  Cargando impresoras...",
            font=fuente(12), text_color=C["text_3"],
        ).pack(pady=20)

        # ── Hardware USB sin driver ───────────────────────────────────────────
        self._seccion(scroll, "Hardware USB Detectado sin Driver")

        ctk.CTkLabel(
            scroll,
            text="Si tu ticketera aparece aquí, instala el driver para poder seleccionarla.",
            font=fuente(11), text_color=C["text_3"],
        ).pack(anchor="w", padx=10, pady=(0, 6))

        hw_border = ctk.CTkFrame(
            scroll, fg_color=C["bg_dark"],
            corner_radius=12, border_color=C["border"], border_width=1)
        hw_border.pack(fill="x", padx=4, pady=(0, 8))

        self._frame_hw = ctk.CTkScrollableFrame(
            hw_border, fg_color="transparent", corner_radius=10, height=110)
        self._frame_hw.pack(fill="x", padx=2, pady=2)
        ctk.CTkLabel(
            self._frame_hw, text="Presiona 🔄 Actualizar para detectar hardware",
            font=fuente(11), text_color=C["text_3"],
        ).pack(pady=14)

        # ── Log de actividad ──────────────────────────────────────────────────
        self._seccion(scroll, "Registro de Actividad")

        self._txt_log = ctk.CTkTextbox(
            scroll, fg_color=C["bg_dark"], text_color=C["text_2"],
            height=60, font=ctk.CTkFont("Courier", 10),
        )
        self._txt_log.pack(fill="x", padx=4, pady=(0, 4))
        self._log("Sistema listo. Presiona 🔄 Actualizar para ver las impresoras.")

        # Auto-escanear al abrir y mostrar el estado actual conocido por main.
        self.after(300, self._escanear)
        self.after(100, self._mostrar_estado_inicial)

    def _mostrar_estado_inicial(self):
        """Lee el estado ya calculado por main y lo aplica al badge sin llamar a WMIC."""
        estado = (
            self._get_estado_imp()
            if self._get_estado_imp
            else {"nivel": "offline", "mensaje": "Verificando..."}
        )
        self._actualizar_estado_badge(estado)

    # ─── Badge de estado de impresora (sin consulta WMIC propia) ─────────────

    def _actualizar_estado_badge(self, estado: dict = None):
        """
        Actualiza el badge visual de la ticketera activa con el estado dado.
        Si no se pasa 'estado', usa el último conocido por main via _get_estado_imp.
        No ejecuta ninguna consulta WMIC — ese trabajo lo hace main.py.
        Solo debe llamarse desde el hilo principal de Tkinter.
        """
        if not self.winfo_exists():
            return

        if estado is None:
            estado = (
                self._get_estado_imp()
                if self._get_estado_imp
                else {"nivel": "offline", "mensaje": "Verificando..."}
            )

        nivel = estado.get("nivel", "offline")
        msg   = estado.get("mensaje", "Sin información")

        if nivel == "ok":
            color_borde  = C["green"]
            color_txt    = C["green"]
            color_titulo = C["green"]
            self._btn_reparar.pack_forget()
        elif nivel == "warning":
            color_borde  = C["yellow"]
            color_txt    = C["yellow"]
            color_titulo = C["text_1"]
            self._btn_reparar.pack_forget()
        elif nivel == "error":
            color_borde  = C["red"]
            color_txt    = C["red"]
            color_titulo = C["text_1"]
            self._log(f"⚠ Error detectado: {msg}")
            self._btn_reparar.pack(side="left")
        else:  # offline
            color_borde  = C["red"]
            color_txt    = C["red"]
            color_titulo = C["text_3"]
            self._btn_reparar.pack(side="left")

        try:
            nombre_mostrar = (
                self._imp_seleccionada
                if self._imp_seleccionada and self._imp_seleccionada != "TicketeraEstacionamiento"
                else "Ninguna (No seleccionada)"
            )
            self._lbl_estado_imp.configure(text=msg, text_color=color_txt)
            self._card_activa.configure(border_color=color_borde)
            self._lbl_imp_activa.configure(
                text=f"🖨️  {nombre_mostrar}",
                text_color=color_titulo,
            )
        except Exception:
            pass

    # ─── Selección de impresora ───────────────────────────────────────────────

    def _seleccionar_impresora(self, nombre: str):
        """Guarda la impresora seleccionada, actualiza la UI y recarga la lista."""
        self._imp_seleccionada = nombre
        self.config.set("impresora", "nombre", nombre)
        from printer import Printer
        self.printer = Printer(nombre)
        self._log(f"✅ Impresora seleccionada: {nombre}")
        self._lbl_imp_activa.configure(text=f"🖨️  {nombre}")
        # Mostrar "Verificando..." hasta que main empuje el estado real (~5 s).
        self._actualizar_estado_badge({"nivel": "warning", "mensaje": "Verificando estado..."})
        if self.on_guardado:
            self.on_guardado()
        self._escanear()

    # ─── Escaneo de impresoras en background ──────────────────────────────────

    def _escanear(self):
        """
        Lanza el escaneo de impresoras instaladas en un hilo daemon.

        BUG FIX (threading): incrementamos _scan_id antes de iniciar el hilo.
        Si el usuario pulsa "Actualizar" varias veces, cada hilo captura su
        propio scan_id. Solo el hilo cuyo scan_id coincide con el actual
        puede actualizar la UI — los hilos obsoletos descartan sus resultados.
        """
        self._scan_id += 1
        scan_id_actual = self._scan_id

        # Limpiar la lista y mostrar indicador de carga
        for w in self._frame_lista.winfo_children():
            w.destroy()
        ctk.CTkLabel(
            self._frame_lista, text="🔄  Escaneando...",
            font=fuente(12), text_color=C["yellow"],
        ).pack(pady=20)

        for w in self._frame_hw.winfo_children():
            w.destroy()
        ctk.CTkLabel(
            self._frame_hw, text="🔄  Escaneando hardware...",
            font=fuente(11), text_color=C["yellow"],
        ).pack(pady=14)

        self._log("Buscando impresoras instaladas y hardware USB...")
        threading.Thread(
            target=lambda: self._scan_worker(scan_id_actual),
            daemon=True,
        ).start()

    def _scan_worker(self, scan_id: int):
        """
        Hilo de trabajo: obtiene la lista de impresoras y hardware.
        Cuando termina, posta el resultado al hilo principal via after().
        El scan_id se propaga para que _mostrar_resultados pueda
        descartar resultados de escaneos ya superados.
        """
        inst       = PrinterInstaller(self._imp_seleccionada)
        impresoras = inst.listar_impresoras_detalle()
        hardware   = inst.listar_hardware_sin_driver()
        # Siempre se vuelve al hilo principal para tocar la UI.
        self.after(0, lambda: self._mostrar_resultados(impresoras, hardware, scan_id))

    def _mostrar_resultados(self, impresoras: List[Dict], hardware: List[Dict], scan_id: int):
        """
        Renderiza los resultados del escaneo en la UI.
        Retorna silenciosamente si el widget ya no existe o si este
        scan_id ya fue superado por un escaneo más reciente.
        """
        if not self.winfo_exists():
            return

        # BUG FIX: descartar resultados de hilos de escaneo obsoletos.
        if scan_id != self._scan_id:
            return

        # ── Renderizar lista de impresoras ────────────────────────────────────
        for w in self._frame_lista.winfo_children():
            w.destroy()

        if not impresoras:
            ctk.CTkLabel(
                self._frame_lista,
                text=(
                    "❌  No se encontraron impresoras instaladas en Windows.\n"
                    "Instala una impresora con driver Generic/Text Only primero."
                ),
                font=fuente(11), text_color=C["red"],
            ).pack(pady=20)
        else:
            for imp in impresoras:
                self._render_imp_card(imp)

        self._log(
            f"Encontradas: {len(impresoras)} impresoras, "
            f"{len(hardware)} dispositivo(s) sin driver."
        )

        # ── Renderizar hardware sin driver ────────────────────────────────────
        for w in self._frame_hw.winfo_children():
            w.destroy()

        if not hardware:
            ctk.CTkLabel(
                self._frame_hw,
                text="✓  No hay hardware sin driver pendiente",
                font=fuente(11), text_color=C["text_3"],
            ).pack(pady=14)
        else:
            for dev in hardware:
                self._render_hw_card(dev)

        # Refrescar badge con el estado actual conocido (sin nueva llamada WMIC).
        self._actualizar_estado_badge()

    def _render_imp_card(self, imp: Dict):
        """Tarjeta para cada impresora instalada en la lista."""
        nombre    = imp["nombre"]
        driver    = imp["driver"]
        puerto    = imp["puerto"]
        es_compat = imp["es_compatible_termica"]
        es_ticket = imp["es_ticketera"]
        es_activa = (nombre == self._imp_seleccionada)

        border_color = C["green"] if es_activa else (C["blue"] if es_compat else C["border"])
        border_w     = 2 if (es_activa or es_compat) else 1
        bg_card      = C["bg_medium"] if es_compat else C["bg_dark"]

        card = ctk.CTkFrame(
            self._frame_lista, fg_color=bg_card, corner_radius=10,
            border_color=border_color, border_width=border_w)
        card.pack(fill="x", padx=8, pady=4)

        left = ctk.CTkFrame(card, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True, padx=14, pady=10)

        top_row = ctk.CTkFrame(left, fg_color="transparent")
        top_row.pack(fill="x")

        name_color = C["green"] if es_activa else C["text_1"]
        ctk.CTkLabel(
            top_row, text=f"🖨️  {nombre}",
            font=fuente(13, bold=True), text_color=name_color, anchor="w",
        ).pack(side="left")

        if es_compat:
            ctk.CTkLabel(
                top_row, text="⭐ Recomendada",
                font=fuente(9, bold=True),
                fg_color=C["blue"], text_color="white",
                corner_radius=8, width=100, height=20,
            ).pack(side="left", padx=(10, 0))
        elif es_ticket:
            ctk.CTkLabel(
                top_row, text="⚠ Driver propio",
                font=fuente(9, bold=True),
                fg_color=C["yellow_h"], text_color="white",
                corner_radius=8, width=100, height=20,
            ).pack(side="left", padx=(10, 0))

        ctk.CTkLabel(
            left, text=f"Driver: {driver}   •   Puerto: {puerto}",
            font=fuente(10), text_color=C["text_3"], anchor="w",
        ).pack(fill="x", pady=(2, 0))

        right = ctk.CTkFrame(card, fg_color="transparent")
        right.pack(side="right", padx=14, pady=10)

        if es_activa:
            ctk.CTkLabel(
                right, text="✓ Seleccionada",
                font=fuente(11, bold=True), text_color=C["green"],
            ).pack()
        elif es_compat:
            ctk.CTkButton(
                right, text="Seleccionar",
                fg_color=C["blue"], hover_color=C["blue_h"],
                text_color="white", font=fuente(11, bold=True),
                width=130, height=32, corner_radius=8,
                command=lambda n=nombre: self._seleccionar_impresora(n),
            ).pack()
        else:
            ctk.CTkButton(
                right, text="🔧 Cambiar Driver\n(Admin)",
                fg_color="#7c2d12", hover_color="#9a3412",
                text_color="white", font=fuente(10, bold=True),
                width=130, height=42, corner_radius=8,
                command=lambda n=nombre: self._cambiar_driver_generico(n),
            ).pack()

    def _render_hw_card(self, dev: Dict):
        """Tarjeta para hardware USB detectado sin driver instalado."""
        nombre = dev.get("nombre", "Desconocido")

        card = ctk.CTkFrame(
            self._frame_hw, fg_color=C["bg_medium"], corner_radius=8,
            border_color=C["yellow"], border_width=1)
        card.pack(fill="x", padx=8, pady=4)

        left = ctk.CTkFrame(card, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True, padx=14, pady=10)

        ctk.CTkLabel(
            left, text=f"🖨️  {nombre}",
            font=fuente(12, bold=True), text_color=C["yellow"], anchor="w",
        ).pack(fill="x")
        ctk.CTkLabel(
            left, text="Sin driver — necesita instalación",
            font=fuente(10), text_color=C["text_3"], anchor="w",
        ).pack(fill="x")

        ctk.CTkButton(
            card, text="🛡️ Instalar\n(Admin)",
            fg_color="#ea580c", hover_color="#c2410c",
            text_color="white", font=fuente(10, bold=True),
            width=110, height=42, corner_radius=8,
            command=lambda n=nombre: self._instalar_driver_admin(n),
        ).pack(side="right", padx=14, pady=10)

    # ─── Cambiar driver a Generic/Text Only ───────────────────────────────────

    def _cambiar_driver_generico(self, nombre_impresora: str):
        """
        Cambia el driver a Generic/Text Only via UAC.
        Necesario para que ESC/POS funcione en ticketeras con driver propio.
        La operación pesada corre en un hilo daemon; la UI se actualiza
        desde el hilo principal via after().
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

        self._log(f"Iniciando cambio de driver para: {nombre_impresora}...")

        def _run():
            inst  = PrinterInstaller(nombre_impresora)
            exito = inst.cambiar_driver_generico(
                nombre_impresora,
                log=lambda m: self.after(0, self._log, m),
            )

            def _ui():
                if not self.winfo_exists():
                    return
                if exito:
                    self._log(f"✅ Driver cambiado. '{nombre_impresora}' ahora usa Generic/Text Only.")
                    messagebox.showinfo(
                        "Driver Actualizado",
                        f"'{nombre_impresora}' ahora usa Generic / Text Only.\n"
                        "Puedes seleccionarla para usarla como ticketera.",
                    )
                    self._escanear()
                else:
                    messagebox.showerror(
                        "Error",
                        "No se pudo cambiar el driver.\n\n"
                        "Posibles causas:\n"
                        "• Rechazaste el permiso de Administrador\n"
                        "• La impresora está en uso\n"
                        "• Windows bloqueó el cambio\n\n"
                        "Intenta de nuevo o hazlo manualmente en:\n"
                        "Dispositivos e Impresoras → Propiedades → Avanzadas → Driver",
                    )

            self.after(0, _ui)

        threading.Thread(target=_run, daemon=True).start()

    # ─── Instalación de driver (hardware sin driver) ──────────────────────────

    def _instalar_driver_admin(self, nombre_modelo: str):
        """
        Instala el driver de una ticketera detectada sin driver.
        La operación pesada corre en un hilo daemon; la UI se actualiza
        desde el hilo principal via after().
        """
        if not messagebox.askyesno(
            "Permisos de Administrador",
            f"Windows pedirá permisos de Administrador para instalar:\n\n{nombre_modelo}\n\n"
            "¿Deseas continuar?",
        ):
            return

        self._log(f"Iniciando instalación como Admin para: {nombre_modelo}...")

        def _run():
            inst = PrinterInstaller(nombre_modelo)
            puerto_detectado = inst.detectar_puerto(
                log=lambda m: self.after(0, self._log, m)
            )
            exito = inst.instalar_como_admin(
                nombre_modelo,
                puerto=puerto_detectado,
                log=lambda m: self.after(0, self._log, m),
            )

            def _ui():
                if not self.winfo_exists():
                    return
                if exito:
                    self._log(f"✅ '{nombre_modelo}' instalada correctamente.")
                    self.config.set("impresora", "nombre", nombre_modelo)
                    self._imp_seleccionada = nombre_modelo
                    self._lbl_imp_activa.configure(text=f"🖨️  {nombre_modelo}")
                    messagebox.showinfo(
                        "Éxito",
                        f"¡'{nombre_modelo}' instalada y seleccionada como ticketera!"
                    )
                    self._escanear()
                    if self.on_guardado:
                        self.on_guardado()
                else:
                    self._log(f"❌ No se pudo instalar '{nombre_modelo}'.")
                    messagebox.showerror(
                        "Error",
                        "No se pudo instalar el driver.\n\n"
                        "Posibles causas:\n"
                        "• Rechazaste el permiso de Administrador\n"
                        "• La ticketera no estaba conectada\n"
                        "• Windows bloqueó la instalación",
                    )

            self.after(0, _ui)

        threading.Thread(target=_run, daemon=True).start()

    # ─── Test de impresión ────────────────────────────────────────────────────

    def _test_impresora(self):
        """
        Envía una página de prueba a la ticketera activa.
        La llamada bloqueante se ejecuta en un hilo daemon para no
        congelar la UI; el resultado se muestra desde el hilo principal.
        """
        inst = PrinterInstaller(self._imp_seleccionada)
        threading.Thread(
            target=lambda: self.after(
                0, self._mostrar_resultado_test, *inst.imprimir_pagina_prueba()
            ),
            daemon=True,
        ).start()

    def _mostrar_resultado_test(self, ok: bool, msg: str):
        self._log(f"{'✅' if ok else '❌'} {msg}")
        if ok:
            messagebox.showinfo("Prueba de Impresión", msg)
        else:
            messagebox.showwarning("Prueba de Impresión", msg)

    # ─── Reparación automática de conexión USB ────────────────────────────────

    def _reparar_impresora(self):
        """
        Intenta reconectar la ticketera buscando su puerto USB actual.
        La operación pesada corre en un hilo daemon; la UI se actualiza
        desde el hilo principal via after().
        """
        if not messagebox.askyesno(
            "Reparar Conexión USB",
            "¿Deseas buscar la ticketera en los puertos USB y reconectarla automáticamente?\n\n"
            "Windows podría pedir permisos de Administrador.",
        ):
            return

        self._log("Iniciando reparación automática de conexión USB...")

        def _run():
            inst  = PrinterInstaller(self._imp_seleccionada)
            exito = inst.reparar_conexion_admin(log=lambda m: self.after(0, self._log, m))

            def _ui():
                if not self.winfo_exists():
                    return
                if exito:
                    self._log("✅ Intento de reparación finalizado.")
                    messagebox.showinfo(
                        "Reparación",
                        "Se actualizó el puerto de la impresora.\n"
                        "Presiona 🧪 Prueba para verificar que todo funciona.",
                    )
                    self._escanear()
                else:
                    self._log("❌ Falló la reparación.")

            self.after(0, _ui)

        threading.Thread(target=_run, daemon=True).start()

    # ─── Helpers de UI ────────────────────────────────────────────────────────

    def _seccion(self, parent, titulo: str):
        """Dibuja un encabezado de sección con línea separadora."""
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.pack(fill="x", padx=4, pady=(16, 4))
        ctk.CTkLabel(
            f, text=titulo, font=fuente(13, bold=True),
            text_color=C["text_2"], anchor="w",
        ).pack(side="left")
        ctk.CTkFrame(f, fg_color=C["border"], height=1).pack(
            side="left", fill="x", expand=True, padx=(10, 0), pady=6)

    def _campo_entrada(self, parent, label: str, valor: str = "") -> ctk.CTkEntry:
        """Fila etiqueta + campo de texto para los formularios de texto libre."""
        fila = ctk.CTkFrame(parent, fg_color="transparent")
        fila.pack(fill="x", padx=4, pady=4)
        ctk.CTkLabel(
            fila, text=label, font=fuente(12), text_color=C["text_2"],
            width=280, anchor="w",
        ).pack(side="left")
        entry = ctk.CTkEntry(
            fila, fg_color=C["bg_dark"], border_color=C["border"],
            text_color=C["text_1"], height=36, width=280)
        entry.insert(0, valor)
        entry.pack(side="right")
        return entry

    def _log(self, texto: str):
        """
        Añade una línea al log de actividad desde el hilo principal.
        BUG FIX: limita el log a _LOG_MAX_LINEAS para evitar que el
        CTkTextbox crezca sin límite y ralentice la aplicación.
        """
        try:
            self._txt_log.configure(state="normal")
            self._txt_log.insert("end", texto + "\n")
            # Eliminar las líneas más antiguas si se supera el límite.
            total = int(self._txt_log.index("end-1c").split(".")[0])
            if total > _LOG_MAX_LINEAS:
                self._txt_log.delete("1.0", f"{total - _LOG_MAX_LINEAS}.0")
            self._txt_log.see("end")
            self._txt_log.configure(state="disabled")
        except Exception:
            pass