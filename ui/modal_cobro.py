"""
ParkingPro - Modal de cobro

Muestra el resumen de la sesión y confirma el cobro e impresión del ticket.

Validaciones:
  • El campo de monto solo acepta dígitos y un punto decimal.
    Cualquier otro carácter se filtra automáticamente al escribir.
  • El monto no puede ser negativo ni un string vacío.

Threading:
  • El cobro y la impresión corren en un hilo del ThreadPoolExecutor
    para no congelar la UI.
  • _procesando (bool) bloquea el botón y la X durante el proceso.
  • Todas las actualizaciones de UI desde el hilo usan after(0, …) +
    winfo_exists() para evitar TclError si la ventana fue cerrada.
  • La conexión SQLite del hilo se cierra explícitamente en el finally.
"""
import math
from concurrent.futures import ThreadPoolExecutor

import customtkinter as ctk
from datetime import datetime
from typing import Dict, Callable, Optional

from ui.theme import C, fuente, color_tipo, hover_tipo, emoji_tipo, TIPO_POR_NOMBRE


# ─── Funciones auxiliares ─────────────────────────────────────────────────────

def calcular_monto(minutos: int, tarifa_hora: float, tiempo_libre: int = 0) -> float:
    """
    Calcula el monto a cobrar.
    Aplica el tiempo libre como periodo de gracia; si el tiempo total no
    supera ese umbral, el cobro es cero.
    Pasado el umbral, se cobra por horas iniciadas sobre los minutos restantes.
    """
    if minutos <= tiempo_libre:
        return 0.0
    minutos_cobrables = minutos - tiempo_libre
    horas = math.ceil(minutos_cobrables / 60)
    return round(horas * tarifa_hora, 2)


def formatear_tiempo(minutos: int) -> str:
    """Convierte minutos a cadena legible: '1h 05min' o '45min'."""
    h = minutos // 60
    m = minutos % 60
    return f"{h}h {m:02d}min" if h > 0 else f"{m}min"


# ─── Modal ────────────────────────────────────────────────────────────────────

class ModalCobro(ctk.CTkToplevel):
    """Ventana modal para registrar el cobro de una sesión activa."""

    def __init__(
        self,
        parent,
        sesion: Dict,
        config,
        db,
        printer,
        on_cobro_exitoso: Optional[Callable[[Dict], None]] = None,
    ):
        super().__init__(parent)
        self.sesion           = sesion
        self.config           = config
        self.db               = db
        self.printer          = printer
        self.on_cobro_exitoso = on_cobro_exitoso

        # Un único hilo para la operación de cobro + impresión
        self._executor = ThreadPoolExecutor(max_workers=1)

        # Bandera de proceso activo: True mientras el hilo está guardando o imprimiendo
        self._procesando = False

        # Bandera anti-recursión para el trace del StringVar de monto
        self._sanitizando_monto = False

        # ── Tamaño proporcional a la pantalla ────────────────────────────────
        _sw = self.winfo_screenwidth()
        _sh = self.winfo_screenheight()
        self._modal_w = max(460, min(600, int(_sw * 0.30)))
        self._modal_h = max(580, min(860, int(_sh * 0.88)))

        # ── Preparar tiempos: congelar segundos para que UI y BD coincidan ───
        self._entrada_dt     = datetime.strptime(sesion["hora_entrada"], "%Y-%m-%d %H:%M:%S")
        self._entrada_limpia = self._entrada_dt.replace(second=0, microsecond=0)
        self._actualizar_reloj_interno()

        # ── Pre-calcular valores de tarifa y monto ───────────────────────────
        self._tarifa     = config.get_tarifa(sesion["tipo_vehiculo"])
        self._tl         = config.get_tiempo_libre()
        self._monto_base = calcular_monto(self._minutos, self._tarifa, self._tl)

        # Colores temáticos del tipo de vehículo
        self._color = color_tipo(sesion["tipo_vehiculo"])
        self._hover = hover_tipo(sesion["tipo_vehiculo"])
        self._emoji = emoji_tipo(sesion["tipo_vehiculo"])

        # ── Configuración de la ventana ───────────────────────────────────────
        self.title("Cobro de Ticket")
        self.geometry(f"{self._modal_w}x{self._modal_h}")
        self.resizable(False, False)
        self.configure(fg_color=C["bg_dark"])
        self.grab_set()   # Bloquea la ventana padre mientras este modal está abierto
        self.lift()
        self.focus_force()

        # Centrar el modal sobre la ventana padre
        self.update_idletasks()
        px = parent.winfo_x() + (parent.winfo_width()  - self._modal_w) // 2
        py = parent.winfo_y() + (parent.winfo_height() - self._modal_h) // 2
        self.geometry(f"{self._modal_w}x{self._modal_h}+{max(0, px)}+{max(0, py)}")

        # Interceptar la X para evitar cierres durante el procesamiento
        self.protocol("WM_DELETE_WINDOW", self._intentar_cerrar)

        self._build_ui()
        self._tick()

    # ─── Ciclo de vida ────────────────────────────────────────────────────────

    def _intentar_cerrar(self):
        """
        Controla el clic en la X de la ventana.
        Si hay un cobro en proceso, ignora el clic para no corromper los datos.
        """
        if self._procesando:
            return
        self.destroy()

    def destroy(self):
        """Apaga el pool de hilos antes de destruir la ventana."""
        if hasattr(self, "_executor"):
            self._executor.shutdown(wait=False)
        super().destroy()

    # ─── Reloj interno ───────────────────────────────────────────────────────

    def _actualizar_reloj_interno(self):
        """
        Congela la hora actual al minuto (sin segundos) y recalcula los minutos
        transcurridos. Mantiene UI y ticket perfectamente sincronizados.
        """
        ahora = datetime.now().replace(second=0, microsecond=0)
        self._hora_salida_str     = ahora.strftime("%Y-%m-%d %H:%M:%S")
        self._hora_salida_display = ahora.strftime("%d/%m/%Y  %I:%M %p")
        self._minutos = max(1, int((ahora - self._entrada_limpia).total_seconds() / 60))

    # ─── Construcción de la UI ────────────────────────────────────────────────

    def _build_ui(self):
        # ── Header coloreado por tipo de vehículo ────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color=self._color, height=76, corner_radius=0)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        ctk.CTkLabel(
            hdr,
            text=f"{self._emoji}  COBRO DE TICKET",
            font=fuente(20, bold=True), text_color="white",
        ).place(relx=0.5, rely=0.40, anchor="center")

        ctk.CTkLabel(
            hdr,
            text=f"Ticket: {self.sesion['ticket_numero']}",
            font=fuente(11), text_color="#c8daf5",
        ).place(relx=0.5, rely=0.78, anchor="center")

        body = ctk.CTkFrame(self, fg_color=C["bg_medium"], corner_radius=0)
        body.pack(fill="both", expand=True)

        # ── Tarjeta: Vehículo ─────────────────────────────────────────────────
        card_veh = ctk.CTkFrame(body, fg_color=C["bg_dark"], corner_radius=12)
        card_veh.pack(fill="x", padx=24, pady=(18, 0))
        self._fila(card_veh, "🚘  Vehículo", f"{self._emoji}  {self.sesion['tipo_vehiculo']}")
        self._fila(
            card_veh, "🔑  Placa", self.sesion["placa"],
            bold_valor=True, color_valor=self._color,
        )

        # ── Tarjeta: Tiempos ──────────────────────────────────────────────────
        card_tiempo = ctk.CTkFrame(body, fg_color=C["bg_dark"], corner_radius=12)
        card_tiempo.pack(fill="x", padx=24, pady=10)
        self._fila(card_tiempo, "🕐  Entrada", self._entrada_dt.strftime("%d/%m/%Y  %I:%M %p"))

        # Estos dos labels se actualizan cada 30 s por _tick()
        self._lbl_salida = self._fila(card_tiempo, "🕐  Salida", self._hora_salida_display)
        self._lbl_tiempo = self._fila(
            card_tiempo, "⏱️  Tiempo total",
            formatear_tiempo(self._minutos), bold_valor=True,
        )

        if self._tl > 0:
            self._fila(card_tiempo, "🎁  Tiempo libre", f"{self._tl} min (tolerancia)")

        self._fila(card_tiempo, "💰  Tarifa", f"{self.config.get_moneda()} {self._tarifa:.2f} / hora")

        # ── Tarjeta: Monto a cobrar ───────────────────────────────────────────
        card_monto = ctk.CTkFrame(
            body, fg_color=C["kpi_bg"], corner_radius=12,
            border_color=self._color, border_width=2,
        )
        card_monto.pack(fill="x", padx=24)

        ctk.CTkLabel(
            card_monto, text="TOTAL A COBRAR",
            font=fuente(11), text_color=C["text_3"],
        ).pack(pady=(14, 2))

        fila_monto = ctk.CTkFrame(card_monto, fg_color="transparent")
        fila_monto.pack(pady=(0, 6))

        ctk.CTkLabel(
            fila_monto, text=self.config.get_moneda(),
            font=fuente(22, bold=True), text_color=C["text_2"],
        ).pack(side="left")

        # StringVar con trace para filtrar caracteres no numéricos en tiempo real
        self._var_monto = ctk.StringVar(value=f"{self._monto_base:.2f}")
        self._var_monto.trace_add("write", self._sanitizar_monto)

        self._entry_monto = ctk.CTkEntry(
            fila_monto,
            textvariable=self._var_monto,
            font=fuente(34, bold=True), text_color=self._color,
            fg_color="transparent", border_width=0,
            width=160, justify="center",
        )
        self._entry_monto.pack(side="left")

        ctk.CTkLabel(
            card_monto,
            text="Edita el monto si necesitas hacer un ajuste manual",
            font=fuente(10), text_color=C["text_3"],
        ).pack(pady=(0, 12))

        # ── Checkbox de impresión ─────────────────────────────────────────────
        self._var_imprimir = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            body, text="Imprimir ticket de salida",
            variable=self._var_imprimir,
            fg_color=self._color, hover_color=self._hover,
            checkmark_color="white",
            text_color=C["text_2"], font=fuente(12),
        ).pack(pady=(14, 0))

        # ── Botones ───────────────────────────────────────────────────────────
        frame_btns = ctk.CTkFrame(body, fg_color="transparent")
        frame_btns.pack(fill="x", padx=24, pady=14)

        ctk.CTkButton(
            frame_btns, text="✕  Cancelar",
            fg_color=C["bg_light"], hover_color=C["border"],
            text_color=C["text_2"], width=180, height=44,
            command=self._cancelar,
        ).pack(side="left", padx=(0, 8))

        self._btn_cobrar = ctk.CTkButton(
            frame_btns, text="✓  Confirmar Cobro",
            fg_color=self._color, hover_color=self._hover,
            text_color="white", font=fuente(14, bold=True),
            width=240, height=44,
            command=self._confirmar,
        )
        self._btn_cobrar.pack(side="right")

        # Label de error (validación de monto)
        self._lbl_error = ctk.CTkLabel(body, text="", font=fuente(11), text_color=C["red"])
        self._lbl_error.pack()

    def _fila(
        self, parent, label: str, valor: str,
        bold_valor: bool = False, color_valor: str = None,
    ) -> ctk.CTkLabel:
        """Crea una fila etiqueta-valor dentro de una tarjeta y devuelve el label de valor."""
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", padx=16, pady=5)
        ctk.CTkLabel(
            frame, text=label,
            font=fuente(12), text_color=C["text_3"],
            width=160, anchor="w",
        ).pack(side="left")
        lbl = ctk.CTkLabel(
            frame, text=valor,
            font=fuente(12, bold=bold_valor),
            text_color=color_valor or C["text_1"],
            anchor="e",
        )
        lbl.pack(side="right")
        return lbl

    # ─── Validación del campo de monto ────────────────────────────────────────

    def _sanitizar_monto(self, *args):
        """
        Trace del StringVar de monto: filtra automáticamente cualquier carácter
        que no sea dígito o punto decimal.
        Solo se permite un punto decimal. Si el usuario pega texto con letras,
        estas se eliminan al instante.
        La bandera _sanitizando_monto evita llamadas recursivas del trace.
        """
        if self._sanitizando_monto:
            return
        self._sanitizando_monto = True
        try:
            raw  = self._var_monto.get()
            limpio = ""
            punto_visto = False
            for ch in raw:
                if ch.isdigit():
                    limpio += ch
                elif ch == '.' and not punto_visto:
                    limpio += ch
                    punto_visto = True
                # Cualquier otro carácter (letras, comas, signos) se descarta
            if limpio != raw:
                self._var_monto.set(limpio)
                # Limpiar el borde de error si el usuario está corrigiendo
                self._entry_monto.configure(border_width=0)
                self._lbl_error.configure(text="")
        finally:
            self._sanitizando_monto = False

    # ─── Timer del modal (actualiza salida y tiempo cada 30 s) ───────────────

    def _tick(self):
        """
        Actualiza la hora de salida y el tiempo transcurrido cada 30 segundos.
        Solo se ejecuta si no hay un cobro en proceso.
        El after() se agenda siempre al final, fuera del bloque condicional,
        para garantizar que el ciclo nunca se detenga por un error puntual.
        """
        if not self.winfo_exists():
            return

        if not self._procesando:
            try:
                self._actualizar_reloj_interno()
                self._lbl_salida.configure(text=self._hora_salida_display)
                self._lbl_tiempo.configure(text=formatear_tiempo(self._minutos))

                # Actualizar el monto solo si el operador no lo modificó manualmente
                monto_actual = None
                try:
                    monto_actual = float(self._var_monto.get())
                except ValueError:
                    pass  # El campo tiene texto inválido temporal; no tocar

                if monto_actual is not None:
                    monto_nuevo = calcular_monto(self._minutos, self._tarifa, self._tl)
                    # Respetar ajuste manual: solo actualizar si no hubo cambio
                    if abs(monto_actual - self._monto_base) < 0.01:
                        self._monto_base = monto_nuevo
                        self._var_monto.set(f"{monto_nuevo:.2f}")

            except Exception:
                # Error al actualizar la pantalla: ignorar para no cortar el ciclo
                pass

        # El after() siempre se agenda, independientemente de cualquier error anterior
        self.after(30_000, self._tick)

    # ─── Acciones ─────────────────────────────────────────────────────────────

    def _cancelar(self):
        """Cierra el modal si no hay un cobro en proceso."""
        if not self._procesando:
            self.destroy()

    def _confirmar(self):
        """
        Valida el monto y lanza el worker de cobro + impresión.
        Bloquea el botón y la X durante todo el proceso.
        """
        # Protección: ignorar si ya hay un cobro en proceso
        if self._procesando:
            return

        # ── Validar monto ─────────────────────────────────────────────────────
        raw_monto = self._var_monto.get().strip()
        if not raw_monto:
            self._entry_monto.configure(border_color=C["red"], border_width=2)
            self._lbl_error.configure(text="⚠ El monto no puede estar vacío")
            return
        try:
            monto = float(raw_monto)
            if monto < 0:
                raise ValueError("negativo")
        except ValueError:
            self._entry_monto.configure(border_color=C["red"], border_width=2)
            self._lbl_error.configure(text="⚠ Ingresa un monto válido (ej: 4.50)")
            return

        imprimir = self._var_imprimir.get()

        # ── Verificar estado de la impresora ──────────────────────────────────
        eleccion = self.printer.verificar_estado_para_proceder(
            self, impresion_solicitada=imprimir
        )
        if eleccion == "intentar":
            # Abortar: el operador fue a revisar la impresora
            return
        elif eleccion == "continuar":
            # El operador decidió continuar sin imprimir
            self._var_imprimir.set(False)
            imprimir = False

        # ── Bloquear UI y lanzar worker ───────────────────────────────────────
        self._procesando = True
        self._entry_monto.configure(border_width=0)
        self._lbl_error.configure(text="")
        self._btn_cobrar.configure(state="disabled", text="⏳  Procesando...")

        sesion = self.sesion

        def _worker():
            """Registra el cobro en BD e imprime el ticket en el hilo secundario."""
            try:
                # Enviar hora y minutos congelados para garantizar consistencia total
                sesion_cobrada = self.db.cobrar_sesion(
                    sesion["id"],
                    monto,
                    minutos_fijos=self._minutos,
                    hora_salida_fija=self._hora_salida_str,
                )

                if "hora_salida" not in sesion_cobrada:
                    raise ValueError(
                        "cobrar_sesion no retornó 'hora_salida'. "
                        "Verifique el módulo database.py."
                    )

                if imprimir:
                    datos = self.config.get_datos_negocio()
                    self.printer.imprimir_cobro(
                        sesion_cobrada,
                        nombre_negocio=self.config.get_nombre_negocio(),
                        tarifa_hora=self._tarifa,
                        moneda=self.config.get_moneda(),
                        direccion=datos["direccion"],
                        telefono=datos["telefono"],
                    )

                def _ok():
                    try:
                        if self.on_cobro_exitoso:
                            self.on_cobro_exitoso(sesion_cobrada)
                    finally:
                        if self.winfo_exists():
                            self.destroy()

                if self.winfo_exists():
                    self.after(0, _ok)

            except Exception as e:
                def _err():
                    # Restaurar la UI para que el operador pueda reintentar
                    self._procesando = False
                    if self.winfo_exists():
                        self._btn_cobrar.configure(
                            state="normal", text="✓  Confirmar Cobro"
                        )
                        self._lbl_error.configure(text=f"⚠ Error: {e}")

                if self.winfo_exists():
                    self.after(0, _err)

            finally:
                # Liberar la conexión SQLite del hilo: evita bloqueos de archivos en Windows
                self.db.cerrar_conexion_actual()

        self._executor.submit(_worker)