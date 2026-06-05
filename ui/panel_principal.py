"""
ParkingPro - Panel Principal (operación diaria)
• Selección de tipo de vehículo
• Registro de placa y entrada
• Tabla en vivo de vehículos activos con timer y cobro
"""
import threading
import customtkinter as ctk
from datetime import datetime
from typing import Dict, List, Optional

from ui.theme import C, TIPOS_VEHICULO, fuente, color_tipo, emoji_tipo
from ui.modal_cobro import ModalCobro, formatear_tiempo, calcular_monto


class PanelPrincipal(ctk.CTkFrame):
    """Panel de operación principal."""

    COLS_TABLA = ["Ticket", "Tipo", "Placa", "Entrada", "⏱ Tiempo", "💰 Estimado", ""]
    COL_ANCHOS = [120, 110, 100, 90, 90, 110, 100]

    def __init__(self, parent, config, db, printer, **kwargs):
        super().__init__(parent, fg_color=C["bg_dark"], corner_radius=0, **kwargs)
        self.config  = config
        self.db      = db
        self.printer = printer

        self._tipo_sel:      Optional[Dict] = None
        self._filas_activas: List[Dict]     = []
        self._tipo_btns:     List[ctk.CTkButton] = []
        self._registrando   = False  # evita doble clic

        self._build_ui()
        self._cargar_activos()
        self._loop_timer()

    def set_printer(self, printer):
        self.printer = printer

    # ─── Construcción de UI ───────────────────────────────────────────────────

    def _build_ui(self):
        # Cabecera
        hdr = ctk.CTkFrame(self, fg_color=C["sidebar"], height=56, corner_radius=0)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text="🅿  Registro de Vehículos",
                     font=fuente(17, bold=True), text_color=C["text_1"]).pack(
            side="left", padx=24)
        self._lbl_activos = ctk.CTkLabel(hdr, text="0 activos",
                                          font=fuente(12), text_color=C["text_3"])
        self._lbl_activos.pack(side="right", padx=24)

        # Panel de entrada
        panel_entrada = ctk.CTkFrame(self, fg_color=C["bg_medium"], corner_radius=0)
        panel_entrada.pack(fill="x")

        ctk.CTkLabel(panel_entrada, text="Selecciona el tipo de vehículo",
                     font=fuente(13), text_color=C["text_2"]).pack(
            anchor="w", padx=28, pady=(16, 6))

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
                width=148, height=74, corner_radius=14,
                command=lambda t=tipo: self._seleccionar_tipo(t),
            )
            btn.grid(row=fila, column=col, padx=6, pady=6)
            self._tipo_btns.append(btn)

        ctk.CTkFrame(panel_entrada, fg_color=C["border"], height=1).pack(
            fill="x", padx=28, pady=(4, 12))

        # Fila placa + registrar
        fila_placa = ctk.CTkFrame(panel_entrada, fg_color="transparent")
        fila_placa.pack(fill="x", padx=28, pady=(0, 16))

        self._lbl_tipo_sel = ctk.CTkLabel(
            fila_placa, text="—  Ningún tipo seleccionado",
            font=fuente(13), text_color=C["text_3"], width=230, anchor="w",
        )
        self._lbl_tipo_sel.pack(side="left")

        self._entry_placa = ctk.CTkEntry(
            fila_placa,
            placeholder_text="Placa: ABC-123",
            font=fuente(15, bold=True), text_color=C["text_1"],
            fg_color=C["bg_dark"], border_color=C["border"], border_width=2,
            height=44, width=180, justify="center",
        )
        self._entry_placa.pack(side="left", padx=(12, 10))
        self._entry_placa.bind("<Return>", lambda e: self._registrar_entrada())

        self._btn_registrar = ctk.CTkButton(
            fila_placa,
            text="➕  Registrar Entrada",
            font=fuente(13, bold=True),
            fg_color=C["blue"], hover_color=C["blue_h"],
            text_color="white", height=44, width=200, corner_radius=10,
            command=self._registrar_entrada,
        )
        self._btn_registrar.pack(side="left")

        self._lbl_msg = ctk.CTkLabel(fila_placa, text="", font=fuente(11), width=200)
        self._lbl_msg.pack(side="left", padx=10)

        # Tabla de activos
        frame_tabla = ctk.CTkFrame(self, fg_color=C["bg_dark"], corner_radius=0)
        frame_tabla.pack(fill="both", expand=True)

        hdr_tabla = ctk.CTkFrame(frame_tabla, fg_color=C["sidebar"],
                                  height=38, corner_radius=0)
        hdr_tabla.pack(fill="x")
        hdr_tabla.pack_propagate(False)

        for i, (col_nombre, w) in enumerate(zip(self.COLS_TABLA, self.COL_ANCHOS)):
            ctk.CTkLabel(
                hdr_tabla, text=col_nombre,
                font=fuente(11, bold=True), text_color=C["text_3"],
                width=w, anchor="w" if i < 6 else "center",
            ).grid(row=0, column=i, padx=(16 if i == 0 else 4, 4), pady=8)

        self._scroll = ctk.CTkScrollableFrame(
            frame_tabla, fg_color=C["bg_dark"],
            scrollbar_fg_color=C["bg_medium"], corner_radius=0,
        )
        self._scroll.pack(fill="both", expand=True)

        self._lbl_vacio = ctk.CTkLabel(
            self._scroll, text="Sin vehículos activos  🅿",
            font=fuente(14), text_color=C["text_3"],
        )
        self._lbl_vacio.pack(pady=40)

    # ─── Selección de tipo ────────────────────────────────────────────────────

    def _seleccionar_tipo(self, tipo: Dict):
        self._tipo_sel = tipo
        for btn, t in zip(self._tipo_btns, TIPOS_VEHICULO):
            seleccionado = (t["nombre"] == tipo["nombre"])
            btn.configure(
                fg_color=tipo["color"] if seleccionado else C["bg_dark"],
                text_color="white" if seleccionado else C["text_2"],
                border_color=tipo["color"] if seleccionado else C["border"],
            )
        tarifa = self.config.get_tarifa(tipo["nombre"])
        moneda = self.config.get_moneda()
        self._lbl_tipo_sel.configure(
            text=f"{tipo['emoji']}  {tipo['nombre']}  •  {moneda}{tarifa:.2f}/hr",
            text_color=tipo["color"],
        )
        self._entry_placa.focus()

    # ─── Registro de entrada ──────────────────────────────────────────────────

    def _registrar_entrada(self):
        if self._registrando:
            return
        placa = self._entry_placa.get().strip().upper()

        if not self._tipo_sel:
            self._mostrar_msg("⚠ Selecciona el tipo de vehículo", C["yellow"])
            return
        if len(placa) < 3:
            self._mostrar_msg("⚠ Escribe la placa del vehículo", C["yellow"])
            self._entry_placa.configure(border_color=C["yellow"])
            return

        self._registrando = True
        self._btn_registrar.configure(state="disabled", text="⏳  Registrando...")

        tipo_nombre = self._tipo_sel["nombre"]

        def _worker():
            try:
                sesion = self.db.registrar_entrada(placa, tipo_nombre)
                self.printer.imprimir_entrada(
                    sesion,
                    nombre_negocio=self.config.get_nombre_negocio(),
                    moneda=self.config.get_moneda(),
                )
                self.after(0, lambda: self._post_registro_ok(placa))
            except ValueError as e:
                self.after(0, lambda: self._post_registro_error(str(e), C["yellow"]))
            except Exception as e:
                self.after(0, lambda: self._post_registro_error(f"Error: {e}", C["red"]))

        threading.Thread(target=_worker, daemon=True).start()

    def _post_registro_ok(self, placa: str):
        self._mostrar_msg(f"✓ {placa} registrado", C["green"])
        self._entry_placa.delete(0, "end")
        self._entry_placa.configure(border_color=C["border"])
        self._btn_registrar.configure(state="normal", text="➕  Registrar Entrada")
        self._registrando = False
        self._cargar_activos()

    def _post_registro_error(self, msg: str, color: str):
        self._mostrar_msg(f"⚠ {msg}", color)
        self._btn_registrar.configure(state="normal", text="➕  Registrar Entrada")
        self._registrando = False

    def _mostrar_msg(self, texto: str, color: str = "white"):
        self._lbl_msg.configure(text=texto, text_color=color)
        self.after(4_000, lambda: self._lbl_msg.configure(text=""))

    # ─── Tabla de activos ─────────────────────────────────────────────────────

    def _cargar_activos(self):
        """Carga la lista de activos desde BD en un hilo daemon."""
        def _worker():
            try:
                activos = self.db.get_sesiones_activas()
                self.after(0, lambda: self._render_activos(activos))
            except Exception:
                pass

        threading.Thread(target=_worker, daemon=True).start()

    def _render_activos(self, activos: List[Dict]):
        if not self.winfo_exists():
            return
        self._filas_activas = activos

        for w in self._scroll.winfo_children():
            w.destroy()

        if not activos:
            self._lbl_vacio = ctk.CTkLabel(
                self._scroll, text="Sin vehículos activos  🅿",
                font=fuente(14), text_color=C["text_3"],
            )
            self._lbl_vacio.pack(pady=40)
            self._lbl_activos.configure(text="0 activos")
            return

        cnt = len(activos)
        self._lbl_activos.configure(
            text=f"{cnt} activo{'s' if cnt != 1 else ''}")

        for idx, sesion in enumerate(activos):
            self._crear_fila(idx, sesion)

    def _crear_fila(self, idx: int, sesion: Dict):
        color_veh = color_tipo(sesion["tipo_vehiculo"])
        bg_fila   = C["bg_medium"] if idx % 2 == 0 else C["bg_dark"]

        fila = ctk.CTkFrame(self._scroll, fg_color=bg_fila, height=50, corner_radius=8)
        fila.pack(fill="x", padx=4, pady=2)
        fila.pack_propagate(False)

        anchos = self.COL_ANCHOS

        # Ticket
        ctk.CTkLabel(fila, text=sesion["ticket_numero"], font=fuente(11),
                     text_color=C["text_3"], width=anchos[0], anchor="w").grid(
            row=0, column=0, padx=(16, 4))

        # Tipo badge
        badge = ctk.CTkFrame(fila, fg_color=color_veh, corner_radius=6,
                              width=96, height=28)
        badge.grid(row=0, column=1, padx=4)
        badge.grid_propagate(False)
        emj = emoji_tipo(sesion["tipo_vehiculo"])
        ctk.CTkLabel(badge, text=f"{emj} {sesion['tipo_vehiculo'][:6]}",
                     font=fuente(11, bold=True), text_color="white",
                     ).place(relx=0.5, rely=0.5, anchor="center")

        # Placa
        ctk.CTkLabel(fila, text=sesion["placa"], font=fuente(13, bold=True),
                     text_color=C["text_1"], width=anchos[2]).grid(row=0, column=2, padx=4)

        # Entrada
        entrada_dt = datetime.strptime(sesion["hora_entrada"], "%Y-%m-%d %H:%M:%S")
        ctk.CTkLabel(fila, text=entrada_dt.strftime("%H:%M"), font=fuente(12),
                     text_color=C["text_2"], width=anchos[3]).grid(row=0, column=3, padx=4)

        # Tiempo (se actualiza cada 30 s)
        minutos = max(0, int((datetime.now() - entrada_dt).total_seconds() / 60))
        lbl_tiempo = ctk.CTkLabel(fila, text=formatear_tiempo(minutos), font=fuente(12),
                                   text_color=C["yellow"], width=anchos[4])
        lbl_tiempo.grid(row=0, column=4, padx=4)

        # Estimado
        tarifa = self.config.get_tarifa(sesion["tipo_vehiculo"])
        monto  = calcular_monto(minutos, tarifa, self.config.get_tiempo_libre())
        lbl_monto = ctk.CTkLabel(
            fila,
            text=f"{self.config.get_moneda()} {monto:.2f}",
            font=fuente(12, bold=True), text_color=C["green"], width=anchos[5],
        )
        lbl_monto.grid(row=0, column=5, padx=4)

        # Botón cobrar
        ctk.CTkButton(
            fila, text="💳 Cobrar",
            fg_color=C["blue"], hover_color=C["blue_h"],
            text_color="white", font=fuente(12, bold=True),
            width=90, height=32, corner_radius=8,
            command=lambda s=sesion: self._abrir_cobro(s),
        ).grid(row=0, column=6, padx=(4, 14))

        # Guardar refs para el timer
        sesion["_lbl_tiempo"] = lbl_tiempo
        sesion["_lbl_monto"]  = lbl_monto
        sesion["_entrada_dt"] = entrada_dt
        sesion["_tarifa"]     = tarifa

    def _abrir_cobro(self, sesion: Dict):
        ModalCobro(
            self.winfo_toplevel(),
            sesion, self.config, self.db, self.printer,
            on_cobro_exitoso=lambda _: self._cargar_activos(),
        )

    # ─── Timer en vivo ────────────────────────────────────────────────────────

    def _loop_timer(self):
        if not self.winfo_exists():
            return
        ahora  = datetime.now()
        moneda = self.config.get_moneda()
        tl     = self.config.get_tiempo_libre()
        for sesion in self._filas_activas:
            lbl_t  = sesion.get("_lbl_tiempo")
            lbl_m  = sesion.get("_lbl_monto")
            ent_dt = sesion.get("_entrada_dt")
            tarifa = sesion.get("_tarifa", 2.0)
            if lbl_t and ent_dt:
                try:
                    mins  = max(0, int((ahora - ent_dt).total_seconds() / 60))
                    monto = calcular_monto(mins, tarifa, tl)
                    lbl_t.configure(text=formatear_tiempo(mins))
                    lbl_m.configure(text=f"{moneda} {monto:.2f}")
                except Exception:
                    pass
        self.after(30_000, self._loop_timer)

    def refrescar(self):
        self._cargar_activos()