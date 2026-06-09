"""
ParkingPro - Modal de cobro
Muestra el resumen de la sesión y confirma el cobro e impresión del ticket.
Threading: el cobro y la impresión corren en hilo daemon para no congelar la UI.
"""
import threading
import customtkinter as ctk
from datetime import datetime
from typing import Dict, Callable, Optional

from ui.theme import C, fuente, color_tipo, hover_tipo, emoji_tipo, TIPO_POR_NOMBRE


# ─── Funciones auxiliares ─────────────────────────────────────────────────────

def calcular_monto(minutos: int, tarifa_hora: float, tiempo_libre: int = 0) -> float:
    """
    Calcula el monto a cobrar según minutos y tarifa por hora.
    """
    if minutos <= tiempo_libre:
        return 0.0
    minutos_cobrables = minutos - tiempo_libre
    import math
    horas = math.ceil(minutos_cobrables / 60)
    return round(horas * tarifa_hora, 2)


def formatear_tiempo(minutos: int) -> str:
    h = minutos // 60
    m = minutos % 60
    if h > 0:
        return f"{h}h {m:02d}min"
    return f"{m}min"


# ─── Modal ────────────────────────────────────────────────────────────────────

class ModalCobro(ctk.CTkToplevel):
    """
    Ventana modal para registrar el cobro de una sesión activa.
    """

    ANCHO = 500
    ALTO  = 600

    def __init__(
        self,
        parent,
        sesion: Dict,
        config,
        db,
        printer,
        on_cobro_exitoso: Callable[[Dict], None] = None,
    ):
        super().__init__(parent)
        self.sesion           = sesion
        self.config           = config
        self.db               = db
        self.printer          = printer
        self.on_cobro_exitoso = on_cobro_exitoso

        self._entrada    = datetime.strptime(sesion["hora_entrada"], "%Y-%m-%d %H:%M:%S")
        self._minutos    = max(1, int((datetime.now() - self._entrada).total_seconds() / 60))
        self._tarifa     = config.get_tarifa(sesion["tipo_vehiculo"])
        self._tl         = config.get_tiempo_libre()
        self._monto_base = calcular_monto(self._minutos, self._tarifa, self._tl)
        self._color      = color_tipo(sesion["tipo_vehiculo"])
        self._hover      = hover_tipo(sesion["tipo_vehiculo"])
        self._emoji      = emoji_tipo(sesion["tipo_vehiculo"])
        self._procesando = False

        self.title("Cobro de Ticket")
        self.geometry(f"{self.ANCHO}x{self.ALTO}")
        self.resizable(False, False)
        self.configure(fg_color=C["bg_dark"])
        self.grab_set()
        self.lift()
        self.focus_force()

        self.update_idletasks()
        px = parent.winfo_x() + (parent.winfo_width()  - self.ANCHO) // 2
        py = parent.winfo_y() + (parent.winfo_height() - self.ALTO)  // 2
        self.geometry(f"{self.ANCHO}x{self.ALTO}+{px}+{py}")

        self._build_ui()
        self._iniciar_timer()

    def _build_ui(self):
        # Header coloreado por tipo de vehículo
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

        # Tarjeta: Vehículo
        card_veh = ctk.CTkFrame(body, fg_color=C["bg_dark"], corner_radius=12)
        card_veh.pack(fill="x", padx=24, pady=(18, 0))
        self._fila(card_veh, "🚘  Vehículo", f"{self._emoji}  {self.sesion['tipo_vehiculo']}")
        self._fila(card_veh, "🔑  Placa", self.sesion["placa"], bold_valor=True, color_valor=self._color)

        # Tarjeta: Tiempos
        card_tiempo = ctk.CTkFrame(body, fg_color=C["bg_dark"], corner_radius=12)
        card_tiempo.pack(fill="x", padx=24, pady=10)
        self._fila(card_tiempo, "🕐  Entrada", self._entrada.strftime("%d/%m/%Y  %I:%M %p"))
        self._fila(card_tiempo, "🕐  Salida (ahora)", datetime.now().strftime("%d/%m/%Y  %I:%M %p"))

        self._lbl_tiempo = self._fila(
            card_tiempo, "⏱️  Tiempo total",
            formatear_tiempo(self._minutos), bold_valor=True,
        )

        if self._tl > 0:
            self._fila(card_tiempo, "🎁  Tiempo libre", f"{self._tl} min (tolerancia)")

        self._fila(card_tiempo, "💰  Tarifa", f"{self.config.get_moneda()} {self._tarifa:.2f} / hora")

        # Tarjeta: Monto
        card_monto = ctk.CTkFrame(body, fg_color=C["kpi_bg"], corner_radius=12, border_color=self._color, border_width=2)
        card_monto.pack(fill="x", padx=24)

        ctk.CTkLabel(card_monto, text="TOTAL A COBRAR", font=fuente(11), text_color=C["text_3"]).pack(pady=(14, 2))

        fila_monto = ctk.CTkFrame(card_monto, fg_color="transparent")
        fila_monto.pack(pady=(0, 6))
        ctk.CTkLabel(fila_monto, text=self.config.get_moneda(), font=fuente(22, bold=True), text_color=C["text_2"]).pack(side="left")

        self._var_monto = ctk.StringVar(value=f"{self._monto_base:.2f}")
        self._entry_monto = ctk.CTkEntry(
            fila_monto, textvariable=self._var_monto,
            font=fuente(34, bold=True), text_color=self._color,
            fg_color="transparent", border_width=0,
            width=160, justify="center",
        )
        self._entry_monto.pack(side="left")

        ctk.CTkLabel(card_monto, text="Edita el monto si necesitas hacer un ajuste manual", font=fuente(10), text_color=C["text_3"]).pack(pady=(0, 12))

        # Opción imprimir
        self._var_imprimir = ctk.BooleanVar(value=True)
        self._chk_imprimir = ctk.CTkCheckBox(
            body, text="Imprimir ticket de salida",
            variable=self._var_imprimir,
            fg_color=self._color, hover_color=self._hover,
            checkmark_color="white",
            text_color=C["text_2"], font=fuente(12),
        )
        self._chk_imprimir.pack(pady=(14, 0))

        # Botones
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
            width=240, height=44, command=self._confirmar,
        )
        self._btn_cobrar.pack(side="right")

        # Label de error
        self._lbl_error = ctk.CTkLabel(body, text="", font=fuente(11), text_color=C["red"])
        self._lbl_error.pack()

    def _fila(self, parent, label: str, valor: str, bold_valor: bool = False, color_valor: str = None) -> ctk.CTkLabel:
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", padx=16, pady=5)
        ctk.CTkLabel(frame, text=label, font=fuente(12), text_color=C["text_3"], width=160, anchor="w").pack(side="left")
        lbl = ctk.CTkLabel(frame, text=valor, font=fuente(12, bold=bold_valor), text_color=color_valor or C["text_1"], anchor="e")
        lbl.pack(side="right")
        return lbl

    def _iniciar_timer(self):
        self._tick()

    def _tick(self):
        if not self.winfo_exists() or self._procesando:
            return
        try:
            minutos = max(1, int((datetime.now() - self._entrada).total_seconds() / 60))
            self._minutos = minutos
            self._lbl_tiempo.configure(text=formatear_tiempo(minutos))

            try:
                monto_actual = float(self._var_monto.get())
                monto_nuevo  = calcular_monto(minutos, self._tarifa, self._tl)
                if abs(monto_actual - self._monto_base) < 0.01:
                    self._monto_base = monto_nuevo
                    self._var_monto.set(f"{monto_nuevo:.2f}")
            except ValueError:
                pass

            self.after(30_000, self._tick)
        except Exception:
            pass

    def _cancelar(self):
        if not self._procesando:
            self.destroy()

    def _confirmar(self):
        if self._procesando:
            return

        # 1. Validar formato del monto
        try:
            monto = float(self._var_monto.get())
            if monto < 0:
                raise ValueError
        except ValueError:
            self._entry_monto.configure(border_color=C["red"], border_width=2)
            self._lbl_error.configure(text="⚠ Ingresa un monto válido")
            return

        imprimir = self._var_imprimir.get()

        # ─── INTERCEPCIÓN DE SEGURIDAD DE IMPRESORA ──────────────────────────
        # Evaluamos el estado del hardware antes de tocar la Base de Datos.
        # Pasamos 'self' como parent para que la alerta modal se centre sobre este Cobro.
        eleccion = self.printer.verificar_estado_para_proceder(self, impresion_solicitada=imprimir)
        
        if eleccion == "intentar":
            return  # Abortamos de inmediato. Nada cambia, la ventana sigue lista.
        elif eleccion == "continuar":
            # Bypass manual: El usuario omitirá el ticket para destrabar la cola
            self._var_imprimir.set(False)
            imprimir = False
        # ─────────────────────────────────────────────────────────────────────

        # El flujo seguro continúa aquí si todo está OK o si se seleccionó Bypass Digital:
        self._procesando = True
        self._entry_monto.configure(border_width=0)
        self._lbl_error.configure(text="")
        self._btn_cobrar.configure(state="disabled", text="⏳  Procesando...")

        sesion = self.sesion

        def _worker():
            try:
                # Modificamos SQLite de forma segura
                sesion_cobrada = self.db.cobrar_sesion(sesion["id"], monto)

                # Si el bypass no se activó, mandamos la orden física de impresión
                if imprimir:
                    datos = self.config.get_datos_negocio()
                    self.printer.imprimir_cobro(
                        sesion_cobrada,
                        nombre_negocio=self.config.get_nombre_negocio(),
                        tarifa_hora=self._tarifa,
                        moneda=self.config.get_moneda(),
                        direccion=datos["direccion"], 
                        telefono=datos["telefono"]
                    )

                def _ok():
                    if self.on_cobro_exitoso:
                        self.on_cobro_exitoso(sesion_cobrada)
                    if self.winfo_exists():
                        self.destroy()

                self.after(0, _ok)

            except Exception as e:
                def _err():
                    self._procesando = False
                    if self.winfo_exists():
                        self._btn_cobrar.configure(state="normal", text="✓  Confirmar Cobro")
                        self._lbl_error.configure(text=f"⚠ Error: {e}")

                self.after(0, _err)

        threading.Thread(target=_worker, daemon=True).start()