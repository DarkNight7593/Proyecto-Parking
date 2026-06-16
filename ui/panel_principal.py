"""
ParkingPro - Panel Principal (operación diaria)

Funcionalidades:
  • Selección de tipo de vehículo con botones de color por categoría.
  • Registro de placa y entrada (con validación y anti-doble-clic).
  • Barra de búsqueda predictiva en tiempo real por placa (Optimizada en memoria).
  • Tabla en vivo de vehículos activos con timer cada 10 s.
  • Botón 💳 Cobrar: abre ModalCobro para procesar el pago.
  • Botón ✕ Cancelar: elimina el registro en caso de error de placa.

Threading (Corregido y Asegurado):
  • El registro de entrada y la carga de activos corren en hilos de un ThreadPoolExecutor.
  • Se incluyó manejo estricto de try/except/finally para evitar hilos zombis y liberar SQLite.
  • El timer de la tabla se ejecuta en el hilo principal (after loop).
"""
import threading
from concurrent.futures import ThreadPoolExecutor
from tkinter import messagebox

import customtkinter as ctk
from datetime import datetime
from typing import Dict, List, Optional

from ui.theme import C, TIPOS_VEHICULO, fuente, color_tipo, emoji_tipo
from ui.modal_cobro import ModalCobro, formatear_tiempo, calcular_monto


class PanelPrincipal(ctk.CTkFrame):
    """Panel de operación principal del estacionamiento."""

    # Cabeceras y anchos de columna de la tabla de activos
    COLS_TABLA = ["Ticket", "Tipo", "Placa", "Entrada", "⏱ Tiempo", "💰 Estimado", "Acciones"]
    COL_ANCHOS = [120,      110,    100,      90,        90,          110,           140]

    def __init__(self, parent, config, db, printer, **kwargs):
        super().__init__(parent, fg_color=C["bg_dark"], corner_radius=0, **kwargs)
        self.config  = config
        self.db      = db
        self.printer = printer

        self._executor = ThreadPoolExecutor(max_workers=3)
        self._cargar_gen = 0

        self._tipo_sel:     Optional[Dict] = None   # tipo de vehículo seleccionado
        self._todos_los_activos: List[Dict] = []     # Caché maestro de activos (para optimizar búsqueda)
        self._filas_activas: List[Dict]     = []     # Lista filtrada/visible en pantalla
        self._tipo_btns:     List[ctk.CTkButton] = [] # botones de tipo de vehículo
        self._registrando = False  # bloqueo anti-doble-clic

        self._build_ui()
        self._cargar_activos()
        self._loop_timer()

    def destroy(self):
        """Se ejecuta al destruir el panel para apagar los hilos limpiamente."""
        self._executor.shutdown(wait=False)
        super().destroy()

    def set_printer(self, printer):
        """Actualiza la impresora desde configuración (llamado por main.py)."""
        self.printer = printer

    # ─── Construcción de la UI ────────────────────────────────────────────────

    def _build_ui(self):
        # ── Métricas de pantalla para layout proporcional ──────────────────
        # winfo_screenwidth/height() devuelven la resolución real del monitor
        # y están disponibles antes de que la ventana sea visible.
        _sw = self.winfo_screenwidth()
        _sh = self.winfo_screenheight()

        # Misma fórmula que main.py para que sidebar_w coincida exactamente
        _sidebar_w = max(200, min(270, int(_sw * 0.155)))
        _avail_w   = _sw - _sidebar_w   # ancho útil real disponible para este panel

        # Botones de tipo de vehículo: 3 columnas, padding lateral ~56 px, gaps 12 px (2×6)
        _btn_w = max(120, min(220, int((_avail_w - 56 - 24) / 3)))
        _btn_h = max(64,  min(90,  int(_sh * 0.09)))

        # Columnas de la tabla: escalar para cubrir el ancho disponible.
        # Los pesos base [120,110,100,90,90,110,140] suman 760 y mantienen proporciones.
        # Se descuentan ~40 px de padding/scrollbar del frame de tabla.
        _base_cols  = [120, 110, 100, 90, 90, 110, 140]
        _net_w      = max(sum(_base_cols), _avail_w - 40)
        _scale      = _net_w / sum(_base_cols)
        _min_cols   = [80, 80, 70, 70, 70, 90, 100]
        self._col_anchos_dyn = [
            max(mn, int(a * _scale)) for a, mn in zip(_base_cols, _min_cols)
        ]
        # ──────────────────────────────────────────────────────────────────

        # ── Cabecera del panel ─────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color=C["sidebar"], height=56, corner_radius=0)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        ctk.CTkLabel(
            hdr, text="🅿  Registro de Vehículos",
            font=fuente(17, bold=True), text_color=C["text_1"],
        ).pack(side="left", padx=24)

        # ── Panel de entrada de datos ──────────────────────────────────────
        panel_entrada = ctk.CTkFrame(self, fg_color=C["bg_medium"], corner_radius=0)
        panel_entrada.pack(fill="x")

        ctk.CTkLabel(
            panel_entrada, text="Selecciona el tipo de vehículo",
            font=fuente(13), text_color=C["text_2"],
        ).pack(anchor="w", padx=28, pady=(16, 6))

        # Grid de botones de tipo de vehículo (2 filas × 3 columnas)
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

        # ── Fila de placa + botón registrar ───────────────────────────────
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

        # Campo de placa con Enter para registrar
        self._entry_placa = ctk.CTkEntry(
            fila_placa,
            placeholder_text="Placa: ABC-123",
            font=fuente(15, bold=True), text_color=C["text_1"],
            fg_color=C["bg_dark"], border_color=C["border"], border_width=2,
            height=44, width=180, justify="center",
        )
        self._entry_placa.pack(side="left", padx=(12, 10))
        self._entry_placa.bind("<Return>", lambda e: self._registrar_entrada())

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
        self._lbl_msg = ctk.CTkLabel(
            fila_placa, text="", font=fuente(11), width=200)
        self._lbl_msg.pack(side="left", padx=10)

        # ── Tabla de vehículos activos ─────────────────────────────────────
        frame_tabla = ctk.CTkFrame(self, fg_color=C["bg_dark"], corner_radius=0)
        frame_tabla.pack(fill="both", expand=True)

        # ── BARRA DE BÚSQUEDA (Optimizada) ───────────────────
        frame_busqueda = ctk.CTkFrame(frame_tabla, fg_color="transparent")
        frame_busqueda.pack(fill="x", padx=24, pady=(12, 8))

        ctk.CTkLabel(
            frame_busqueda, text="🔍 Buscar por Placa:",
            font=fuente(12, bold=True), text_color=C["text_2"]
        ).pack(side="left", padx=(0, 8))

        self._entry_buscar = ctk.CTkEntry(
            frame_busqueda,
            placeholder_text="Escribe para buscar...",
            font=fuente(12), text_color=C["text_1"],
            fg_color=C["bg_medium"], border_color=C["border"], border_width=1,
            height=30, width=220,
        )
        self._entry_buscar.pack(side="left")
        # Enlazar la pulsación de teclas al método de filtrado rápido
        self._entry_buscar.bind("<KeyRelease>", lambda e: self._aplicar_filtro())

        # Cabecera de la tabla
        hdr_tabla = ctk.CTkFrame(
            frame_tabla, fg_color=C["sidebar"], height=38, corner_radius=0)
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

        # Mensaje inicial cuando no hay activos
        self._lbl_vacio = ctk.CTkLabel(
            self._scroll,
            text="Sin vehículos activos  🅿",
            font=fuente(14), text_color=C["text_3"],
        )
        self._lbl_vacio.pack(pady=40)

    # ─── Selección de tipo de vehículo ────────────────────────────────────────

    def _seleccionar_tipo(self, tipo: Dict):
        """
        Marca el tipo seleccionado visualmente y muestra la tarifa.
        Cambia el estilo del botón activo y resetea los demás.
        """
        self._tipo_sel = tipo

        for btn, t in zip(self._tipo_btns, TIPOS_VEHICULO):
            seleccionado = (t["nombre"] == tipo["nombre"])
            btn.configure(
                fg_color=tipo["color"] if seleccionado else C["bg_dark"],
                text_color="white"    if seleccionado else C["text_2"],
                border_color=tipo["color"] if seleccionado else C["border"],
            )

        # Mostrar tarifa configurada para este tipo
        tarifa = self.config.get_tarifa(tipo["nombre"])
        moneda = self.config.get_moneda()
        self._lbl_tipo_sel.configure(
            text=f"{tipo['emoji']}  {tipo['nombre']}  •  {moneda}{tarifa:.2f}/hr",
            text_color=tipo["color"],
        )
        self._entry_placa.focus()

    # ─── Registro de entrada ──────────────────────────────────────────────────

    def _registrar_entrada(self):
        """
        Valida los datos y registra la entrada en un hilo del pool.
        Bloquea el botón durante el proceso para evitar registros dobles.
        """
        if self._registrando:
            return

        placa = self._entry_placa.get().strip().upper()

        # Validaciones antes de lanzar el hilo
        if not self._tipo_sel:
            self._mostrar_msg("⚠ Selecciona el tipo de vehículo", C["yellow"])
            return
        if len(placa) < 3:
            self._mostrar_msg("⚠ Escribe la placa del vehículo", C["yellow"])
            self._entry_placa.configure(border_color=C["yellow"])
            return
        
        # Security check centralizado de la ticketera
        imprimir_entrada = self.config.getbool("impresora", "activa", fallback=True)
        eleccion = self.printer.verificar_estado_para_proceder(self, impresion_solicitada=imprimir_entrada)
        
        if eleccion == "intentar":
            return  # Aborta el registro para que arreglen la ticketera. No entra en SQLite.
        elif eleccion == "continuar":
            imprimir_entrada = False  # El cajero bypassó el error para entrar sin ticket físico

        self._registrando = True
        self._btn_registrar.configure(state="disabled", text="⏳  Registrando...")
        tipo_nombre = self._tipo_sel["nombre"]

        def _worker():
            """Registra en BD e imprime el ticket de entrada."""
            try:
                sesion = self.db.registrar_entrada(placa, tipo_nombre)
                
                # Ejecuta la impresión sólo si pasó el filtro de seguridad
                if imprimir_entrada:
                    datos = self.config.get_datos_negocio() 
                    self.printer.imprimir_entrada(
                        sesion,
                        nombre_negocio=self.config.get_nombre_negocio(),
                        direccion=datos["direccion"], 
                        telefono=datos["telefono"]
                    )
                
                # CORRECCIÓN: Validamos winfo_exists() ANTES de planificar el after para evitar TclError
                if self.winfo_exists():
                    self.after(0, lambda: self._post_registro_ok(placa))

            except ValueError as e:
                # CORRECCIÓN: Restablece de forma segura el control de errores si ocurre una excepción de negocio
                if self.winfo_exists():
                    self.after(0, lambda: self._post_registro_error(str(e), C["yellow"]))
            except Exception as e:
                # CORRECCIÓN: Evita el estado congelado (zombi) del botón ante un error crítico imprevisto
                if self.winfo_exists():
                    self.after(0, lambda: self._post_registro_error(f"Error: {e}", C["red"]))
            finally:
                # CORRECCIÓN CRUCIAL: Limpia siempre la conexión de SQLite asignada al hilo secundario del pool
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
        """Muestra el error y restaura el formulario."""
        if not self.winfo_exists(): 
            return

        self._mostrar_msg(f"⚠ {msg}", color)
        self._btn_registrar.configure(state="normal", text="➕  Registrar Entrada")
        self._registrando = False

    def _mostrar_msg(self, texto: str, color: str = "white"):
        """Muestra un mensaje temporal (desaparece en 4 segundos)."""
        if not self.winfo_exists():
            return
        self._lbl_msg.configure(text=texto, text_color=color)
        self.after(4_000, lambda: self._limpiar_msg_seguro())

    def _limpiar_msg_seguro(self):
        """Limpia de forma segura el label de estado validando la existencia del widget."""
        if self.winfo_exists():
            self._lbl_msg.configure(text="")

    # ─── Tabla de vehículos activos y Filtrado ────────────────────────────────

    def _cargar_activos(self):
        self._cargar_gen += 1
        gen = self._cargar_gen          # captura la generación actual
        def _worker():
            try:
                activos = self.db.get_sesiones_activas()
                if self.winfo_exists() and self._cargar_gen == gen:  # ← solo postea si sigue siendo el más nuevo
                    self.after(0, lambda: self._post_cargar_activos(activos))
            except Exception:
                pass
            finally:
                self.db.cerrar_conexion_actual()
        self._executor.submit(_worker)

    def _post_cargar_activos(self, activos: List[Dict]):
        """Almacena la lista completa en memoria y procesa el filtro actual."""
        if not self.winfo_exists(): 
            return

        self._todos_los_activos = activos
        self._aplicar_filtro()

    def _aplicar_filtro(self):
        """Filtra la lista de vehículos en memoria según lo escrito por el usuario."""
        if not self.winfo_exists():
            return

        busqueda = self._entry_buscar.get().strip().upper()

        if not busqueda:
            self._render_activos(self._todos_los_activos)
        else:
            # Filtrado rápido en memoria (aquellos que EMPIEZAN con los caracteres ingresados)
            filtrados = [
                sesion for sesion in self._todos_los_activos
                if sesion["placa"].upper().startswith(busqueda)
            ]
            self._render_activos(filtrados)

    def _render_activos(self, activos: List[Dict]):
        """Renderiza la tabla de activos en el hilo principal destruyendo previos widgets."""
        if not self.winfo_exists():
            return

        self._filas_activas = activos

        # Limpiar tabla anterior
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
        """Crea una fila gráfica en la tabla para una sesión activa."""
        if not self.winfo_exists():
            return

        color_veh = color_tipo(sesion["tipo_vehiculo"])
        bg_fila = C["bg_medium"] if idx % 2 == 0 else C["bg_dark"]

        fila = ctk.CTkFrame(self._scroll, fg_color=bg_fila, height=50, corner_radius=8)
        fila.pack(fill="x", padx=4, pady=2)
        fila.pack_propagate(False)

        anchos = self._col_anchos_dyn   # anchos proporcionales calculados en _build_ui

        # Columna 0: Número de ticket
        ctk.CTkLabel(
            fila, text=sesion["ticket_numero"],
            font=fuente(11), text_color=C["text_3"],
            width=anchos[0], anchor="w",
        ).grid(row=0, column=0, padx=(16, 4))

        # Columna 1: Badge de tipo
        badge = ctk.CTkFrame(fila, fg_color=color_veh, corner_radius=6, width=96, height=28)
        badge.grid(row=0, column=1, padx=4)
        badge.grid_propagate(False)
        emj = emoji_tipo(sesion["tipo_vehiculo"])
        ctk.CTkLabel(
            badge, text=f"{emj} {sesion['tipo_vehiculo'][:6]}",
            font=fuente(11, bold=True), text_color="white",
        ).place(relx=0.5, rely=0.5, anchor="center")

        # Columna 2: Placa
        ctk.CTkLabel(
            fila, text=sesion["placa"],
            font=fuente(13, bold=True), text_color=C["text_1"],
            width=anchos[2],
        ).grid(row=0, column=2, padx=4)

        # Procesar tiempos sin incluir segundos
        entrada_dt = datetime.strptime(sesion["hora_entrada"], "%Y-%m-%d %H:%M:%S")
        entrada_limpia = entrada_dt.replace(second=0, microsecond=0)
        ahora_limpio = datetime.now().replace(second=0, microsecond=0)

        # Columna 3: Hora de entrada (HH:MM)
        ctk.CTkLabel(
            fila, text=entrada_dt.strftime("%H:%M"),
            font=fuente(12), text_color=C["text_2"],
            width=anchos[3],
        ).grid(row=0, column=3, padx=4)

        # Columna 4: Tiempo transcurrido
        minutos = max(1, int((ahora_limpio - entrada_limpia).total_seconds() / 60))
        lbl_tiempo = ctk.CTkLabel(
            fila, text=formatear_tiempo(minutos),
            font=fuente(12), text_color=C["yellow"],
            width=anchos[4],
        )
        lbl_tiempo.grid(row=0, column=4, padx=4)

        # Columna 5: Monto estimado
        tarifa = self.config.get_tarifa(sesion["tipo_vehiculo"])
        monto  = calcular_monto(minutos, tarifa, self.config.get_tiempo_libre())
        lbl_monto = ctk.CTkLabel(
            fila, text=f"{self.config.get_moneda()} {monto:.2f}",
            font=fuente(12, bold=True), text_color=C["green"],
            width=anchos[5],
        )
        lbl_monto.grid(row=0, column=5, padx=4)

        # Columna 6: Botones de acción (Cobrar + Cancelar)
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

        # Guardar metadatos para el loop del timer en UI
        sesion["_lbl_tiempo"]     = lbl_tiempo
        sesion["_lbl_monto"]      = lbl_monto
        sesion["_entrada_dt"]     = entrada_dt
        sesion["_entrada_limpia"] = entrada_limpia
        sesion["_tarifa"]         = tarifa

    def _abrir_cobro(self, sesion: Dict):
        """Abre el modal de cobro para la sesión seleccionada."""
        if not self.winfo_exists():
            return
        ModalCobro(
            self.winfo_toplevel(),
            sesion, self.config, self.db, self.printer,
            on_cobro_exitoso=lambda _: self._cargar_activos(),
        )

    def _cancelar_sesion(self, sesion: Dict):
        """Cancela un registro activo tras confirmación explícita."""
        if not self.winfo_exists():
            return

        placa  = sesion.get("placa", "")
        ticket = sesion.get("ticket_numero", "")

        confirmado = messagebox.askyesno(
            "Cancelar Registro",
            f"¿Eliminar el registro de la placa  {placa}?\n"
            f"Ticket: {ticket}\n\n"
            f"No se registrará el cobro del ticket\n\n"
            f"¿Confirmas la cancelación?",
        )

        if not confirmado:
            return

        try:
            self.db.cancelar_sesion(sesion["id"])
            self._cargar_activos()
            self._mostrar_msg(f"✓ Registro {ticket} cancelado", C["yellow"])
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo cancelar el registro:\n{e}")
        finally:
            # CORRECCIÓN: Libera la conexión tras ejecutar la query en el hilo principal de UI
            self.db.cerrar_conexion_actual()

    # ─── Timer en vivo (actualiza tiempo y monto cada 10 s) ──────────────────

    def _loop_timer(self):
        """Loop principal del timer. Se ejecuta en el hilo de UI cada 10 segundos."""
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

            if not (lbl_t and ent_limpia):
                continue

            try:
                # Los cálculos se ejecutan sobre widgets validados y existentes
                if lbl_t.winfo_exists() and lbl_m.winfo_exists():
                    mins  = max(1, int((ahora_limpio - ent_limpia).total_seconds() / 60))
                    monto = calcular_monto(mins, tarifa, tl)
                    lbl_t.configure(text=formatear_tiempo(mins))
                    lbl_m.configure(text=f"{moneda} {monto:.2f}")
            except Exception:
                pass

        # Programar siguiente actualización recursiva en 10 segundos
        self.after(10_000, self._loop_timer)

    def refrescar(self):
        """API pública para que otros paneles fuercen un refresco de la tabla."""
        if self.winfo_exists():
            self._cargar_activos()