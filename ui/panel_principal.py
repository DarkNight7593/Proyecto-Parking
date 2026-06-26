"""
ParkingPro - Panel Principal (operación diaria)

Funcionalidades:
  • Selección de tipo de vehículo con botones de color por categoría.
  • Registro de placa y entrada (con validación de formato, filtro de caracteres
    en tiempo real y protección anti-doble-clic).
  • Búsqueda predictiva en tiempo real por placa (filtrado en memoria).
  • Tabla en vivo de vehículos activos con timer cada 10 s.
  • Botón 💳 Cobrar: abre ModalCobro para procesar el pago.
  • Botón ✕ Cancelar: marca el registro como 'cancelado' en la BD.

Formato de placa aceptado:
  • Cualquier combinación de letras (A-Z), dígitos (0-9) y guión opcional.
  • Mínimo 2 caracteres (letra o dígito); sin restricción de dígitos.
  • Máximo 8 caracteres en total (con o sin guión).
  • Siempre almacenado en MAYÚSCULAS.

Threading:
  • max_workers=3: registro, carga de activos y cancelación pueden correr en paralelo.
  • _registrando (bool) actúa como semáforo para evitar registros simultáneos.
    Solo se lee y escribe desde el hilo UI → no necesita Lock.
  • Todos los callbacks al hilo UI se hacen por after() con winfo_exists() previo.
  • Las conexiones SQLite del pool se cierran explícitamente en el finally de cada worker.
"""
import re
from concurrent.futures import ThreadPoolExecutor
from tkinter import messagebox

import customtkinter as ctk
from datetime import datetime
from typing import Dict, List, Optional

from ui.theme import C, TIPOS_VEHICULO, fuente, color_tipo, emoji_tipo
from ui.modal_cobro import ModalCobro, formatear_tiempo, calcular_monto


# ─── Constante de validación de placa ────────────────────────────────────────
# Caracteres permitidos: cualquier letra unicode (incluye tildes/ñ), dígitos 0-9
# y guión '-' (sin restricción de orden). El mismo criterio se usa en el filtro
# en tiempo real de _on_placa_cambia, para que ambas validaciones coincidan.
# ⚠ Si en algún momento se requiere restringir solo a A-Z (sin tildes ni otros
#   alfabetos), cambiar esta regex a r'^[A-Z0-9-]+$' y ajustar el filtro de
#   _on_placa_cambia (que hoy acepta ch.isalpha() de cualquier idioma).
# Requisito mínimo: al menos 2 caracteres (letra o dígito).
# Requisito máximo: no superar PLACA_MAX_CHARS caracteres en total (con o sin guión).
PLACA_CHARS_RE = re.compile(r'^[\w-]+$')


# Máximo de caracteres permitidos en el campo de placa (8 caracteres)
PLACA_MAX_CHARS = 10

# Texto de placeholder del campo de placa. Es más largo que PLACA_MAX_CHARS
# a propósito (es solo un texto de ejemplo, no una placa real), por lo que
# el validador de longitud (_validar_longitud_placa) le hace una excepción
# explícita para no bloquear su inserción cuando el campo está vacío.
PLACA_PLACEHOLDER = "Placa: ABC-123"


class PanelPrincipal(ctk.CTkFrame):
    """Panel de operación principal del estacionamiento."""

    # Cabeceras y pesos base de columna de la tabla de activos
    COLS_TABLA = ["Ticket", "Tipo", "Placa", "Entrada", "⏱ Tiempo", "💰 Estimado", "Acciones"]
    COL_BASES  = [120,      110,    100,      90,        90,          110,           140]

    def __init__(self, parent, config, db, printer, **kwargs):
        super().__init__(parent, fg_color=C["bg_dark"], corner_radius=0, **kwargs)
        self.config  = config
        self.db      = db
        self.printer = printer

        # Pool de hilos: 3 workers (registro + carga de activos + cancelación)
        self._executor = ThreadPoolExecutor(max_workers=3)

        # Generación del último worker de carga (evita que un worker viejo
        # sobreescriba la tabla tras una recarga más reciente)
        self._cargar_gen = 0

        # Estado interno de la UI
        self._tipo_sel:          Optional[Dict]       = None   # tipo de vehículo seleccionado
        self._todos_los_activos: List[Dict]           = []     # caché maestro para búsqueda en memoria
        self._filas_activas:     List[Dict]           = []     # lista actualmente visible en tabla
        self._tipo_btns:         List[ctk.CTkButton]  = []     # botones de tipo de vehículo

        # Semáforo de registro: True mientras hay un hilo de BD registrando entrada
        self._registrando = False

        # Bandera anti-recursión para _on_placa_cambia: evita que el propio
        # filtro (delete/insert al reescribir el texto) vuelva a dispararse
        # a sí mismo. Ya no hay StringVar/trace para la placa (se eliminó al
        # cambiar a validación por evento <KeyRelease> directo sobre el Entry).
        self._procesando_placa = False

        self._build_ui()
        self._cargar_activos()
        self._loop_timer()

    def destroy(self):
        """Apaga el pool de hilos limpiamente antes de destruir el frame."""
        self._executor.shutdown(wait=False)
        super().destroy()

    def set_printer(self, printer):
        """Actualiza la impresora (llamado desde main.py al cambiar config)."""
        self.printer = printer

    # ─── Construcción de la UI ────────────────────────────────────────────────

    def _build_ui(self):
        # ── Métricas de pantalla para layout proporcional ─────────────────────
        _sw = self.winfo_screenwidth()
        _sh = self.winfo_screenheight()

        # Ancho del sidebar (igual que en main.py para que coincidan)
        _sidebar_w = max(200, min(270, int(_sw * 0.155)))
        _avail_w   = _sw - _sidebar_w  # ancho útil disponible para este panel

        # Botones de tipo de vehículo: 3 columnas con padding lateral ~56 px y gap 12 px
        _btn_w = max(120, min(220, int((_avail_w - 56 - 24) / 3)))
        _btn_h = max(64,  min(90,  int(_sh * 0.09)))

        # Columnas de la tabla: escaladas al ancho disponible
        _net_w     = max(sum(self.COL_BASES), _avail_w - 40)
        _scale     = _net_w / sum(self.COL_BASES)
        _min_cols  = [80, 80, 70, 70, 70, 90, 100]
        self._col_anchos_dyn = [
            max(mn, int(a * _scale)) for a, mn in zip(self.COL_BASES, _min_cols)
        ]

        # ── Cabecera del panel ────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color=C["sidebar"], height=56, corner_radius=0)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        ctk.CTkLabel(
            hdr, text="🅿  Registro de Vehículos",
            font=fuente(17, bold=True), text_color=C["text_1"],
        ).pack(side="left", padx=24)

        # ── Panel de entrada de datos ─────────────────────────────────────────
        panel_entrada = ctk.CTkFrame(self, fg_color=C["bg_medium"], corner_radius=0)
        panel_entrada.pack(fill="x")

        ctk.CTkLabel(
            panel_entrada, text="Selecciona el tipo de vehículo",
            font=fuente(13), text_color=C["text_2"],
        ).pack(anchor="w", padx=28, pady=(16, 6))

        # Grid de botones de tipo de vehículo (N filas × 3 columnas)
        frame_tipos = ctk.CTkFrame(panel_entrada, fg_color="transparent")
        frame_tipos.pack(padx=20, pady=(0, 12))

        for i, tipo in enumerate(TIPOS_VEHICULO):
            fila, col = divmod(i, 3)
            btn = ctk.CTkButton(
                frame_tipos,
                text=f"{tipo['emoji']}\n{tipo['nombre']}",
                font=fuente(13, bold=True),
                fg_color=C["bg_dark"],
                hover_color=tipo["color"],
                text_color=C["text_2"],
                border_color=C["border"], border_width=1,
                width=_btn_w, height=_btn_h, corner_radius=14,
                command=lambda t=tipo: self._seleccionar_tipo(t),
            )
            btn.grid(row=fila, column=col, padx=6, pady=6)
            self._tipo_btns.append(btn)

        # Separador
        ctk.CTkFrame(panel_entrada, fg_color=C["border"], height=1).pack(
            fill="x", padx=28, pady=(4, 12))

        # ── Fila de placa + botón registrar ──────────────────────────────────
        fila_placa = ctk.CTkFrame(panel_entrada, fg_color="transparent")
        fila_placa.pack(fill="x", padx=28, pady=(0, 16))

        # Label que muestra el tipo y tarifa seleccionados
        self._lbl_tipo_sel = ctk.CTkLabel(
            fila_placa,
            text="—  Ningún tipo seleccionado",
            font=fuente(13), text_color=C["text_3"],
            width=230, anchor="w",
        )
        self._lbl_tipo_sel.pack(side="left")

        # Validador nativo de Tkinter: se ejecuta ANTES de aplicar cualquier
        # inserción/borrado en el Entry (tecleo, autorepeat de una tecla
        # mantenida presionada, pegado con Ctrl+V o clic central, o una
        # inserción programática), y la rechaza si el resultado supera
        # PLACA_MAX_CHARS. A diferencia del filtro en _on_placa_cambia
        # (que corrige el texto DESPUÉS de insertarlo, en <KeyRelease>),
        # este nunca deja que el Entry llegue a tener más de 8 caracteres,
        # así que no existe ninguna ventana de tiempo en la que un
        # autorepeat o un pegado puedan "inflar" la placa antes de Enter.
        _vcmd_placa = (self.register(self._validar_longitud_placa), '%P')

        # Campo de placa con Enter para registrar (SIN textvariable)
        self._entry_placa = ctk.CTkEntry(
            fila_placa,
            placeholder_text=PLACA_PLACEHOLDER,
            font=fuente(15, bold=True), text_color=C["text_1"],
            fg_color=C["bg_dark"], border_color=C["border"], border_width=2,
            height=44, width=180, justify="center",
            validate="key", validatecommand=_vcmd_placa,
        )
        self._entry_placa.pack(side="left", padx=(12, 10))
        
        # Binds de teclado
        self._entry_placa.bind("<Return>", lambda e: self._registrar_entrada())
        self._entry_placa.bind("<KeyRelease>", self._on_placa_cambia)  # Limpieza visual (mayúsculas, charset) tras cada tecla

        # Botón principal de registro
        self._btn_registrar = ctk.CTkButton(
            fila_placa,
            text="➕  Registrar Entrada",
            font=fuente(13, bold=True),
            fg_color=C["blue"], hover_color=C["blue_h"],
            text_color="white", height=44, width=200, corner_radius=10,
            command=self._registrar_entrada,
        )
        self._btn_registrar.pack(side="left")

        # Label de mensaje temporal (OK, error, warning)
        self._lbl_msg = ctk.CTkLabel(fila_placa, text="", font=fuente(11), width=200)
        self._lbl_msg.pack(side="left", padx=10)

        # ── Tabla de vehículos activos ────────────────────────────────────────
        frame_tabla = ctk.CTkFrame(self, fg_color=C["bg_dark"], corner_radius=0)
        frame_tabla.pack(fill="both", expand=True)

        # Barra de búsqueda por placa (filtrado en memoria)
        frame_busqueda = ctk.CTkFrame(frame_tabla, fg_color="transparent")
        frame_busqueda.pack(fill="x", padx=24, pady=(12, 8))

        ctk.CTkLabel(
            frame_busqueda, text="🔍 Buscar por Placa:",
            font=fuente(12, bold=True), text_color=C["text_2"],
        ).pack(side="left", padx=(0, 8))

        self._entry_buscar = ctk.CTkEntry(
            frame_busqueda,
            placeholder_text="Escribe para buscar...",
            font=fuente(12), text_color=C["text_1"],
            fg_color=C["bg_medium"], border_color=C["border"], border_width=1,
            height=30, width=220,
        )
        self._entry_buscar.pack(side="left")
        self._entry_buscar.bind("<KeyRelease>", lambda e: self._aplicar_filtro())

        # Cabecera de la tabla
        hdr_tabla = ctk.CTkFrame(frame_tabla, fg_color=C["sidebar"], height=38, corner_radius=0)
        hdr_tabla.pack(fill="x")
        hdr_tabla.pack_propagate(False)

        for i, (col_nombre, w) in enumerate(zip(self.COLS_TABLA, self._col_anchos_dyn)):
            ctk.CTkLabel(
                hdr_tabla, text=col_nombre,
                font=fuente(11, bold=True), text_color=C["text_3"],
                width=w, anchor="w" if i < 6 else "center",
            ).grid(row=0, column=i, padx=(16 if i == 0 else 4, 4), pady=8)

        # Área scrollable para las filas de vehículos
        self._scroll = ctk.CTkScrollableFrame(
            frame_tabla, fg_color=C["bg_dark"],
            scrollbar_fg_color=C["bg_medium"], corner_radius=0,
        )
        self._scroll.pack(fill="both", expand=True)

        # Label inicial cuando no hay activos
        self._lbl_vacio = ctk.CTkLabel(
            self._scroll,
            text="Sin vehículos activos  🅿",
            font=fuente(14), text_color=C["text_3"],
        )
        self._lbl_vacio.pack(pady=40)

    # ─── Selección de tipo de vehículo ────────────────────────────────────────

    def _seleccionar_tipo(self, tipo: Dict):
        """
        Marca visualmente el tipo seleccionado y actualiza la tarifa mostrada.
        Resetea el estilo de todos los demás botones.
        """
        self._tipo_sel = tipo

        for btn, t in zip(self._tipo_btns, TIPOS_VEHICULO):
            seleccionado = (t["nombre"] == tipo["nombre"])
            btn.configure(
                fg_color=tipo["color"] if seleccionado else C["bg_dark"],
                text_color="white"    if seleccionado else C["text_2"],
                border_color=tipo["color"] if seleccionado else C["border"],
            )

        tarifa = self.config.get_tarifa(tipo["nombre"])
        moneda = self.config.get_moneda()
        self._lbl_tipo_sel.configure(
            text=f"{tipo['emoji']}  {tipo['nombre']}  •  {moneda}{tarifa:.2f}/hr",
            text_color=tipo["color"],
        )
        self._entry_placa.focus()

    # ─── Validación de placa en tiempo real ──────────────────────────────────

    def _validar_longitud_placa(self, valor_propuesto: str) -> bool:
        """
        Validador nativo de Tkinter (validate='key') para el Entry de placa.

        Tkinter llama a esta función ANTES de aplicar cualquier inserción o
        borrado en el widget, con 'valor_propuesto' = el texto que quedaría
        en el campo SI se permite la operación (substitución %P). Si esta
        función devuelve False, Tkinter descarta la edición por completo y
        el contenido del Entry no cambia en absoluto.

        Esto es lo que cierra el hueco de _on_placa_cambia (que corrige el
        texto recién DESPUÉS de insertarlo, en <KeyRelease>): aquí el campo
        NUNCA llega a superar PLACA_MAX_CHARS, sin importar si el exceso
        viene de teclear normal, de mantener una tecla presionada
        (autorepeat), de un pegado (Ctrl+V / clic central) o de un insert()
        programático.

        Solo valida longitud; el filtrado de charset y mayúsculas sigue a
        cargo de _on_placa_cambia, que no se toca.
        """
        # Excepción explícita: el placeholder ("Placa: ABC-123") es más
        # largo que PLACA_MAX_CHARS a propósito (es un texto de ejemplo,
        # no una placa real). CTkEntry lo inserta completo de una sola vez
        # cuando el campo está vacío, así que dejarlo pasar no abre ningún
        # hueco para placas reales.
        if valor_propuesto == PLACA_PLACEHOLDER:
            return True
        return len(valor_propuesto) <= PLACA_MAX_CHARS

    def _on_placa_cambia(self, event=None):
        """
        Validación por evento: filtra caracteres inválidos y convierte a mayúsculas.
        Solo permite letras A-Z, dígitos 0-9 y el guión '-', máximo PLACA_MAX_CHARS caracteres.
        """
        # Ignorar teclas de control (flechas, borrar, shift, tab) para no trabar el cursor
        if event and event.keysym in ('BackSpace', 'Left', 'Right', 'Up', 'Down', 'Shift_L', 'Shift_R', 'Tab'):
            self._entry_placa.configure(border_color=C["border"])
            return

        # Enter: NO tocar el borde aquí. El KeyPress de <Return> ya disparó
        # _registrar_entrada() (que puede pintar el borde rojo/amarillo si la
        # validación falla); el KeyRelease del mismo Enter llega después y,
        # si no se ignora, resetea ese borde de error apenas se pintó.
        if event and event.keysym == 'Return':
            return

        if getattr(self, "_procesando_placa", False):
            return
            
        self._procesando_placa = True
        try:
            # Obtenemos el texto directo del Entry
            raw = self._entry_placa.get()
            
            # Cortafuegos: si está vacío, dejamos que el placeholder haga su magia
            if not raw:
                self._entry_placa.configure(border_color=C["border"])
                return

            # Filtrar: solo A-Z, 0-9 y guión; máximo PLACA_MAX_CHARS
            limpio = "".join(
                ch.upper() for ch in raw
                if ch.isalpha() or ch.isdigit() or ch == '-'
            )[:PLACA_MAX_CHARS]
            
            # Si el texto cambió (escribió en minúsculas o metió un símbolo raro)
            if limpio != raw:
                # Guardamos dónde estaba el cursor para que no salte al inicio
                cursor_pos = self._entry_placa.index("insert")
                
                # Reemplazamos el texto en el widget
                self._entry_placa.delete(0, "end")
                self._entry_placa.insert(0, limpio)
                
                # Restauramos la posición del cursor
                self._entry_placa.icursor(cursor_pos)
                
            self._entry_placa.configure(border_color=C["border"])
        finally:
            self._procesando_placa = False

    # ─── Registro de entrada ──────────────────────────────────────────────────

    def _registrar_entrada(self):
        """
        Valida la placa y el tipo de vehículo, luego registra la entrada en BD
        usando un hilo del pool. El flag _registrando impide registros simultáneos.
        """
        # Protección anti-doble-clic: si ya hay un registro en curso, salir
        if self._registrando:
            return

        placa = self._entry_placa.get().strip().upper()

        # ── Validaciones en el hilo principal (sin tocar la BD) ──────────────
        if not self._tipo_sel:
            self._mostrar_msg("⚠ Selecciona el tipo de vehículo", C["yellow"])
            return

        if not placa:
            self._mostrar_msg("⚠ Escribe la placa del vehículo", C["yellow"])
            self._entry_placa.configure(border_color=C["yellow"])
            return

        # Validar caracteres permitidos: letras, dígitos y guión
        if not PLACA_CHARS_RE.match(placa):
            self._mostrar_msg("⚠ Solo letras, números y guión permitidos", C["red"])
            self._entry_placa.configure(border_color=C["red"])
            return

        # Validar longitud mínima: al menos 2 caracteres (letra o dígito)
        if len(placa) < 2:
            self._mostrar_msg("⚠ La placa debe tener al menos 2 caracteres", C["red"])
            self._entry_placa.configure(border_color=C["red"])
            return

        # Validar longitud máxima: segundo candado, independiente del
        # validador nativo del Entry (validate='key'). En condiciones
        # normales el campo nunca debería llegar hasta aquí con más de
        # PLACA_MAX_CHARS caracteres, pero esta comprobación se mantiene
        # como respaldo final antes de tocar la BD (igual que ya se hace
        # con la placa duplicada, validada también en database.py).
        if len(placa) > PLACA_MAX_CHARS:
            self._mostrar_msg(f"⚠ La placa no puede superar {PLACA_MAX_CHARS} caracteres", C["red"])
            self._entry_placa.configure(border_color=C["red"])
            return

        # Verificar estado de la impresora antes de continuar con la BD
        imprimir_entrada = self.config.getbool("impresora", "activa", fallback=True)
        eleccion = self.printer.verificar_estado_para_proceder(
            self, impresion_solicitada=imprimir_entrada
        )
        if eleccion == "intentar":
            # El operador fue a revisar la impresora; abortar sin tocar la BD
            return
        elif eleccion == "continuar":
            # El operador decidió continuar sin imprimir
            imprimir_entrada = False

        # ── Bloquear UI y lanzar worker ──────────────────────────────────────
        self._registrando = True
        self._btn_registrar.configure(state="disabled", text="⏳  Registrando...")
        tipo_nombre = self._tipo_sel["nombre"]

        def _worker():
            """Registra en BD e imprime el ticket de entrada en el hilo secundario."""
            try:
                sesion = self.db.registrar_entrada(placa, tipo_nombre)

                if imprimir_entrada:
                    datos = self.config.get_datos_negocio()
                    self.printer.imprimir_entrada(
                        sesion,
                        nombre_negocio=self.config.get_nombre_negocio(),
                        direccion=datos["direccion"],
                        telefono=datos["telefono"],
                    )

                if self.winfo_exists():
                    self.after(0, lambda: self._post_registro_ok(placa))

            except ValueError as e:
                # Error de negocio conocido (ej. placa duplicada)
                if self.winfo_exists():
                    self.after(0, lambda: self._post_registro_error(str(e), C["yellow"]))
            except Exception as e:
                # Error técnico inesperado
                if self.winfo_exists():
                    self.after(0, lambda: self._post_registro_error(f"Error: {e}", C["red"]))
            finally:
                # Liberar la conexión SQLite del hilo para evitar bloqueos en Windows
                self.db.cerrar_conexion_actual()

        self._executor.submit(_worker)

    def _post_registro_ok(self, placa: str):
        """Limpia el formulario y recarga la tabla tras un registro exitoso."""
        if not self.winfo_exists():
            return
        self._mostrar_msg(f"✓ {placa} registrado", C["green"])
        self._entry_placa.delete(0, "end")
        self._entry_placa.configure(border_color=C["border"])
        self._btn_registrar.configure(state="normal", text="➕  Registrar Entrada")
        self._registrando = False
        self._cargar_activos()

    def _post_registro_error(self, msg: str, color: str):
        """Muestra el error y restaura el formulario para reintentar."""
        if not self.winfo_exists():
            return
        self._mostrar_msg(f"⚠ {msg}", color)
        self._entry_placa.configure(border_color=color)
        self._btn_registrar.configure(state="normal", text="➕  Registrar Entrada")
        self._registrando = False

    def _mostrar_msg(self, texto: str, color: str = "white"):
        """Muestra un mensaje de estado que desaparece automáticamente en 4 segundos."""
        if not self.winfo_exists():
            return
        self._lbl_msg.configure(text=texto, text_color=color)
        self.after(4_000, self._limpiar_msg_seguro)

    def _limpiar_msg_seguro(self):
        """Limpia el label de estado verificando que el widget siga existiendo."""
        if self.winfo_exists():
            self._lbl_msg.configure(text="")

    # ─── Carga y renderizado de la tabla de activos ──────────────────────────

    def _cargar_activos(self):
        """
        Lanza un worker para leer sesiones activas de la BD.
        Usa un contador de generación (_cargar_gen) para descartar resultados
        obsoletos si se lanza una nueva carga antes de que termine la anterior.
        """
        self._cargar_gen += 1
        gen = self._cargar_gen  # captura la generación actual en el cierre

        def _worker():
            try:
                activos = self.db.get_sesiones_activas()
                # Solo postear si sigue siendo la carga más reciente
                if self.winfo_exists() and self._cargar_gen == gen:
                    self.after(0, lambda: self._post_cargar_activos(activos))
            except Exception as e:
                err = str(e)
                if self.winfo_exists() and self._cargar_gen == gen:
                    self.after(0, lambda: self._mostrar_msg(
                        f"⚠ Error al cargar tabla: {err}", C["red"]
                    ))
            finally:
                self.db.cerrar_conexion_actual()

        self._executor.submit(_worker)

    def _post_cargar_activos(self, activos: List[Dict]):
        """Almacena el caché maestro en memoria y aplica el filtro de búsqueda activo."""
        if not self.winfo_exists():
            return
        self._todos_los_activos = activos
        self._aplicar_filtro()

    def _aplicar_filtro(self):
        """
        Filtra la lista de activos en memoria según el texto del buscador.
        No accede a la BD; opera siempre sobre _todos_los_activos.
        """
        if not self.winfo_exists():
            return
        busqueda = self._entry_buscar.get().strip().upper()
        if not busqueda:
            self._render_activos(self._todos_los_activos)
        else:
            filtrados = [
                s for s in self._todos_los_activos
                if s["placa"].upper().startswith(busqueda)
            ]
            self._render_activos(filtrados)

    def _render_activos(self, activos: List[Dict]):
        """
        Renderiza la tabla destruyendo los widgets anteriores y reconstruyendo.
        Solo se llama desde el hilo principal (via after()).
        """
        if not self.winfo_exists():
            return

        self._filas_activas = activos

        # Destruir todos los widgets previos en el scroll
        for w in self._scroll.winfo_children():
            w.destroy()

        if not activos:
            ctk.CTkLabel(
                self._scroll,
                text="Sin vehículos activos  🅿",
                font=fuente(14), text_color=C["text_3"],
            ).pack(pady=40)
            return

        for idx, sesion in enumerate(activos):
            self._crear_fila(idx, sesion)

    def _crear_fila(self, idx: int, sesion: Dict):
        """Crea una fila gráfica completa para una sesión activa en la tabla."""
        if not self.winfo_exists():
            return

        color_veh = color_tipo(sesion["tipo_vehiculo"])
        bg_fila   = C["bg_medium"] if idx % 2 == 0 else C["bg_dark"]

        fila = ctk.CTkFrame(self._scroll, fg_color=bg_fila, height=50, corner_radius=8)
        fila.pack(fill="x", padx=4, pady=2)
        fila.pack_propagate(False)

        anchos = self._col_anchos_dyn

        # Columna 0: Número de ticket
        ctk.CTkLabel(
            fila, text=sesion["ticket_numero"],
            font=fuente(11), text_color=C["text_3"],
            width=anchos[0], anchor="w",
        ).grid(row=0, column=0, padx=(16, 4))

        # Columna 1: Badge de tipo de vehículo
        badge = ctk.CTkFrame(fila, fg_color=color_veh, corner_radius=6, width=96, height=28)
        badge.grid(row=0, column=1, padx=4)
        badge.grid_propagate(False)
        ctk.CTkLabel(
            badge,
            text=f"{emoji_tipo(sesion['tipo_vehiculo'])} {sesion['tipo_vehiculo'][:6]}",
            font=fuente(11, bold=True), text_color="white",
        ).place(relx=0.5, rely=0.5, anchor="center")

        # Columna 2: Placa
        # Truncar placas largas (datos corruptos existentes) para no romper el layout.
        # Formato normal: máx 8 chars. Si es más largo, mostrar primeros 8 + "…"
        placa_raw     = sesion["placa"]
        placa_display = placa_raw if len(placa_raw) <= PLACA_MAX_CHARS else placa_raw[:PLACA_MAX_CHARS] + "…"
        ctk.CTkLabel(
            fila, text=placa_display,
            font=fuente(13, bold=True), text_color=C["text_1"],
            width=anchos[2],
        ).grid(row=0, column=2, padx=4)

        # Calcular tiempos sin incluir segundos (consistente con el modal de cobro)
        entrada_dt     = datetime.strptime(sesion["hora_entrada"], "%Y-%m-%d %H:%M:%S")
        entrada_limpia = entrada_dt.replace(second=0, microsecond=0)
        ahora_limpio   = datetime.now().replace(second=0, microsecond=0)

        # Columna 3: Hora de entrada (HH:MM)
        ctk.CTkLabel(
            fila, text=entrada_dt.strftime("%H:%M"),
            font=fuente(12), text_color=C["text_2"],
            width=anchos[3],
        ).grid(row=0, column=3, padx=4)

        # Columna 4: Tiempo transcurrido (actualizable por _loop_timer)
        minutos   = max(1, int((ahora_limpio - entrada_limpia).total_seconds() / 60))
        lbl_tiempo = ctk.CTkLabel(
            fila, text=formatear_tiempo(minutos),
            font=fuente(12), text_color=C["yellow"],
            width=anchos[4],
        )
        lbl_tiempo.grid(row=0, column=4, padx=4)

        # Columna 5: Monto estimado (actualizable por _loop_timer)
        tarifa    = self.config.get_tarifa(sesion["tipo_vehiculo"])
        monto     = calcular_monto(minutos, tarifa, self.config.get_tiempo_libre())
        lbl_monto = ctk.CTkLabel(
            fila,
            text=f"{self.config.get_moneda()} {monto:.2f}",
            font=fuente(12, bold=True), text_color=C["green"],
            width=anchos[5],
        )
        lbl_monto.grid(row=0, column=5, padx=4)

        # Columna 6: Botones de acción
        frame_btns = ctk.CTkFrame(fila, fg_color="transparent")
        frame_btns.grid(row=0, column=6, padx=(4, 10))

        ctk.CTkButton(
            frame_btns, text="💳 Cobrar",
            fg_color=C["blue"], hover_color=C["blue_h"],
            text_color="white", font=fuente(11, bold=True),
            width=82, height=32, corner_radius=8,
            command=lambda s=sesion: self._abrir_cobro(s),
        ).pack(side="left")

        ctk.CTkButton(
            frame_btns, text="✕",
            fg_color="#4a1010", hover_color=C["red"],
            text_color="#ff8080", font=fuente(12, bold=True),
            width=36, height=32, corner_radius=8,
            command=lambda s=sesion: self._cancelar_sesion(s),
        ).pack(side="left", padx=(5, 0))

        # Guardar referencias de labels en el dict de sesión para el timer
        sesion["_lbl_tiempo"]     = lbl_tiempo
        sesion["_lbl_monto"]      = lbl_monto
        sesion["_entrada_dt"]     = entrada_dt
        sesion["_entrada_limpia"] = entrada_limpia
        sesion["_tarifa"]         = tarifa

    # ─── Acciones de la tabla ────────────────────────────────────────────────

    def _abrir_cobro(self, sesion: Dict):
        """
        Abre el modal de cobro para la sesión indicada.
        grab_set() en el modal impide que el operador interactúe con la tabla
        mientras el cobro está en curso, por lo que no se necesita lock adicional.
        """
        if not self.winfo_exists():
            return
        ModalCobro(
            self.winfo_toplevel(),
            sesion, self.config, self.db, self.printer,
            on_cobro_exitoso=lambda _: self._cargar_activos(),
        )

    def _cancelar_sesion(self, sesion: Dict):
        """
        Marca la sesión como 'cancelado' en la BD tras confirmación explícita.
        La operación corre en un worker del pool para no bloquear la UI mientras
        SQLite procesa el UPDATE (podría estar ocupado con otro worker).
        """
        if not self.winfo_exists():
            return

        placa     = sesion.get("placa", "")
        ticket    = sesion.get("ticket_numero", "")
        sesion_id = sesion["id"]   # capturar ID antes del hilo; el dict no es thread-safe

        confirmado = messagebox.askyesno(
            "Cancelar Registro",
            f"¿Cancelar el registro de la placa  {placa}?\n"
            f"Ticket: {ticket}\n\n"
            f"El registro quedará como 'cancelado' en la BD (no se elimina).\n\n"
            f"¿Confirmas la cancelación?",
        )
        if not confirmado:
            return

        def _on_ok():
            if not self.winfo_exists():
                return
            self._cargar_activos()
            self._mostrar_msg(f"✓ Registro {ticket} cancelado", C["yellow"])

        def _worker():
            try:
                self.db.cancelar_sesion(sesion_id)
                if self.winfo_exists():
                    self.after(0, _on_ok)
            except Exception as e:
                err = str(e)
                if self.winfo_exists():
                    self.after(0, lambda: messagebox.showerror(
                        "Error", f"No se pudo cancelar el registro:\n{err}"
                    ))
            finally:
                # Liberar la conexión SQLite del hilo del pool
                self.db.cerrar_conexion_actual()

        self._executor.submit(_worker)

    # ─── Timer en vivo (actualiza tiempo y monto cada 10 s) ──────────────────

    def _loop_timer(self):
        """
        Actualiza los labels de tiempo y monto estimado de cada fila activa.
        Se ejecuta íntegramente en el hilo de UI cada 10 segundos.
        No accede a la BD; opera solo sobre los widgets ya renderizados.
        """
        if not self.winfo_exists():
            return

        ahora_limpio = datetime.now().replace(second=0, microsecond=0)
        moneda = self.config.get_moneda()
        tl     = self.config.get_tiempo_libre()

        for sesion in self._filas_activas:
            lbl_t      = sesion.get("_lbl_tiempo")
            lbl_m      = sesion.get("_lbl_monto")
            ent_limpia = sesion.get("_entrada_limpia")
            tarifa     = sesion.get("_tarifa", 2.0)

            if not (lbl_t and lbl_m and ent_limpia):
                continue

            try:
                # Verificar existencia de widgets antes de configurarlos
                if lbl_t.winfo_exists() and lbl_m.winfo_exists():
                    mins  = max(1, int((ahora_limpio - ent_limpia).total_seconds() / 60))
                    monto = calcular_monto(mins, tarifa, tl)
                    lbl_t.configure(text=formatear_tiempo(mins))
                    lbl_m.configure(text=f"{moneda} {monto:.2f}")
            except Exception:
                # Widget destruido entre la verificación y el configure; ignorar
                pass

        if self.winfo_exists():
            self.after(10_000, self._loop_timer)

    # ─── API pública ─────────────────────────────────────────────────────────

    def refrescar(self):
        """Permite que otros paneles fuercen un refresco de la tabla desde fuera."""
        if self.winfo_exists():
            self._cargar_activos()