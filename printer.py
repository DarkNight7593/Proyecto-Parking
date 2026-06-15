"""
ParkingPro - Módulo de impresión ESC/POS
Compatible con ticketeras via win32print (Windows).
En sistemas no-Windows funciona en modo simulación (print en consola).

Detección de estado usa WMIC (Win32_Printer) para capturar desconexiones USB
en tiempo real, mucho más fiable que el Status del spooler de Windows.
"""
import os
from datetime import datetime
from typing import Dict

try:
    import win32print
    WINDOWS_PRINT = True
except ImportError:
    WINDOWS_PRINT = False

# ─── Comandos ESC/POS ─────────────────────────────────────────────────────────
ESC = b'\x1b'
GS  = b'\x1d'

INIT         = ESC + b'@'
ALIGN_LEFT   = ESC + b'a\x00'
ALIGN_CENTER = ESC + b'a\x01'
ALIGN_RIGHT  = ESC + b'a\x02'
TXT_NORMAL   = ESC + b'!\x00'
TXT_DOUBLE   = ESC + b'!\x30'
BOLD_ON      = ESC + b'E\x01'
BOLD_OFF     = ESC + b'E\x00'
CUT_FULL     = ESC + b'i'
CUT_GS       = GS  + b'V\x00'

ANCHO_TICKET = 42

# ─── Mapa de estados win32print (PRINTER_INFO_2.Status) ──────────────────────
_STATUS_MAP = [
    (0x00000002, "error",   "⚠ Error general"),
    (0x00000008, "error",   "⚠ Papel atascado"),
    (0x00000010, "error",   "⚠ Sin papel"),
    (0x00000040, "error",   "⚠ Problema de papel"),
    (0x00000080, "error",   "⚠ Offline"),
    (0x00100000, "error",   "⚠ Intervención manual"),
    (0x00400000, "error",   "⚠ Cubierta abierta"),
    (0x00040000, "error",   "⚠ Sin papel/tinta"),
    (0x00200000, "error",   "⚠ Sin memoria"),
    (0x00020000, "warning", "⚠ Papel/tinta bajo"),
    (0x00000001, "warning", "⏸ Pausada"),
    (0x00001000, "warning", "⚠ No disponible"),
    (0x00000200, "warning", "⏳ Ocupada"),
    (0x00000400, "ok",      "🖨 Imprimiendo..."),
    (0x00004000, "ok",      "⚙ Procesando..."),
    (0x00008000, "ok",      "⚙ Inicializando..."),
    (0x00010000, "ok",      "⚙ Calentando..."),
]

# PRINTER_ATTRIBUTE_WORK_OFFLINE flag
_ATTR_WORK_OFFLINE = 0x00000400


class Printer:
    """
    Gestiona la comunicación directa con la ticketera via win32print (RAW).
    En no-Windows, simula la salida en consola.

    """

    def __init__(self, nombre_impresora: str):
        self.nombre_impresora = nombre_impresora

    # ─── Envío RAW ────────────────────────────────────────────────────────────

    def _enviar_raw(self, datos: bytes) -> bool:
        if not WINDOWS_PRINT:
            print("[Simulación] Datos enviados a impresora.")
            return True
        try:
            h = win32print.OpenPrinter(self.nombre_impresora)
            try:
                win32print.StartDocPrinter(h, 1, ("Ticket ParkingPro", None, "RAW"))
                win32print.StartPagePrinter(h)
                win32print.WritePrinter(h, datos)
                win32print.EndPagePrinter(h)
                win32print.EndDocPrinter(h)
            finally:
                win32print.ClosePrinter(h)
            return True
        except Exception as e:
            print(f"[ERROR Impresora] {e}")
            return False
        
# ─── NUEVO: Obtener estado real y detallado de la ticketera ────────────────
    def get_estado_detallado(self) -> dict:
        """
        Consulta el estado de hardware de la impresora usando la API de Windows.
        Retorna un diccionario con 'nivel' ('ok', 'warning', 'error', 'offline') y 'mensaje'.
        """
        if not WINDOWS_PRINT:
            return {"nivel": "ok", "mensaje": "✓ Modo Simulación Activo (No-Windows)"}
        try:
            h = win32print.OpenPrinter(self.nombre_impresora)
            try:
                info = win32print.GetPrinter(h, 2)
                status = info.get("Status", 0)
                attributes = info.get("Attributes", 0)

                # Verificar si el spooler la marcó como offline descuidada
                if attributes & _ATTR_WORK_OFFLINE:
                    return {"nivel": "offline", "mensaje": "✗ Desconectada / Offline"}

                # Evaluar las banderas de error mediante tu mapa de bits
                for mask, nivel, msg in _STATUS_MAP:
                    if status & mask:
                        return {"nivel": nivel, "mensaje": msg}

                return {"nivel": "ok", "mensaje": "✓ Lista para operar"}
            finally:
                win32print.ClosePrinter(h)
        except Exception as e:
            return {"nivel": "error", "mensaje": f"✗ Error de comunicación: {e}"}

    # ─── NUEVO: Interceptor de seguridad con Ventana Emergente Congelante ─────
    def verificar_estado_para_proceder(self, parent, impresion_solicitada: bool = True) -> str:
        """
        Comprueba el estado de la ticketera. Si falla, despliega un modal superpuesto
        bloqueante usando grab_set(). 
        Retorna 'intentar' (frenar proceso) o 'continuar' (proceder sin imprimir).
        """
        # Si el operador desmarcó la casilla de impresión, procedemos directo
        if not impresion_solicitada:
            return "ok"   # FIX: era "continuar" — el código llamador trata "continuar"
                          # como "no imprimir", así que con "ok" se respeta el estado
                          # real de imprimir_entrada/imprimir sin forzar False.

        estado = self.get_estado_detallado()
        if estado["nivel"] == "ok":
            return "ok"   # FIX: era "continuar" — esto hacía que NUNCA se imprimiera
                          # aunque la ticketera funcionara perfectamente, porque ambos
                          # sitios de llamada (panel_principal y modal_cobro) tratan
                          # "continuar" como señal de bypass (no imprimir).
                          # Semántica correcta: "ok" = todo bien, proceder con la
                          # impresión; "continuar" = usuario eligió omitir el ticket.

        import customtkinter as ctk

        # Variable síncrona para capturar la decisión del usuario en el hilo principal
        resultado = ctk.StringVar(value="intentar")

        # Configuración de la ventana flotante modal
        dialog = ctk.CTkToplevel(parent)
        dialog.title("⚠ Alerta de Comunicación")
        dialog.geometry("460x220")
        dialog.resizable(False, False)
        dialog.transient(parent)
        dialog.grab_set()  # <<< CONGELA Y BLOQUEA EL PANEL INFERIOR COMPLETAMENTE

        # Centrar la ventana flotante sobre el panel que la llamó
        dialog.update_idletasks()
        try:
            x = parent.winfo_x() + (parent.winfo_width() // 2) - (460 // 2)
            y = parent.winfo_y() + (parent.winfo_height() // 2) - (220 // 2)
            dialog.geometry(f"+{x}+{y}")
        except Exception:
            pass

        # Interfaz Estética e Impactante
        ctk.CTkLabel(
            dialog, 
            text="⚠ ALERTA: TICKETERA NO DISPONIBLE", 
            font=("Arial", 14, "bold"), 
            text_color="#ff4d4d"
        ).pack(pady=(20, 10))

        detalle = f"La impresora reporta anomalías o se encuentra desconectada.\n[Detalle]: {estado['mensaje']}\n\n¿Desea pausar para solucionar o continuar todo el proceso sin ticket?"
        ctk.CTkLabel(
            dialog, 
            text=detalle, 
            font=("Arial", 11), 
            justify="center",
            wraplength=410
        ).pack(pady=5, padx=20)

        frame_btns = ctk.CTkFrame(dialog, fg_color="transparent")
        frame_btns.pack(pady=(20, 10), fill="x", padx=20)

        def _on_intentar():
            resultado.set("intentar")
            dialog.destroy()

        def _on_continuar():
            resultado.set("continuar")
            dialog.destroy()

        btn_intentar = ctk.CTkButton(
            frame_btns, 
            text="⏳ Intentar Luego (Pausar)", 
            fg_color="#2b2b2b", 
            hover_color="#3a3a3a", 
            height=36,
            command=_on_intentar
        )
        btn_intentar.pack(side="left", expand=True, padx=5)

        btn_continuar = ctk.CTkButton(
            frame_btns, 
            text="✔ Continuar sin Imprimir", 
            fg_color="#0d3321", 
            hover_color="#134e32", 
            text_color="#2ecc71",
            font=("Arial", 12, "bold"),
            height=36,
            command=_on_continuar
        )
        btn_continuar.pack(side="right", expand=True, padx=5)

        parent.wait_window(dialog)  # Congela la ejecución del código invocador aquí
        return resultado.get()

# ─── Constructores de líneas ──────────────────

    def _l(self, texto: str = "") -> bytes:
        return (texto[:ANCHO_TICKET] + "\n").encode("latin-1", errors="replace")

    def _sep(self, char: str = "-") -> bytes:  
        return self._l(char * ANCHO_TICKET)

    def _sep2(self) -> bytes:             
        return self._l("=" * ANCHO_TICKET)

    def _centro(self, texto: str) -> bytes:
        return ALIGN_CENTER + self._l(texto)

    def _par(self, izq: str, der: str) -> bytes:
        espacio = max(1, ANCHO_TICKET - len(izq) - len(der))
        return ALIGN_LEFT + self._l(izq + " " * espacio + der)

    # ─── Ticket de entrada optimizado ─────────────────────────────────────────

    def imprimir_entrada(self, sesion: Dict, nombre_negocio: str = "PARKING",
                         direccion: str = "", telefono: str = "") -> bool:

        ahora = datetime.strptime(sesion["hora_entrada"], "%Y-%m-%d %H:%M:%S")

        buf = bytearray()
        buf += INIT
        buf += CUT_FULL
        buf += b'\n' * 2

        buf += ALIGN_CENTER
        buf += BOLD_ON + TXT_DOUBLE
        buf += self._l(f"  {nombre_negocio}  ")
        buf += BOLD_OFF + TXT_NORMAL
        
        # Parámetros condicionales de la captura (Excluyendo RUC por completo)
        if direccion.strip():
            buf += self._l(direccion.strip())
        if telefono.strip():
            buf += self._l(f"Tel: {telefono.strip()}")
            
        buf += self._sep2()

        buf += ALIGN_LEFT
        buf += self._par("Ticket N°:", sesion["ticket_numero"])
        buf += self._par("Fecha:",     ahora.strftime("%d/%m/%Y"))
        buf += self._par("Hora:",      ahora.strftime("%I:%M %p"))
        buf += self._sep()

        buf += ALIGN_CENTER
        buf += BOLD_ON
        buf += self._l(f"Vehiculo: {sesion['tipo_vehiculo'].upper()}")
        buf += BOLD_OFF

        buf += ALIGN_LEFT
        buf += self._par("Placa:", sesion["placa"])
        buf += self._sep2()

        buf += ALIGN_CENTER
        buf += self._l("Conserve este ticket")
        buf += self._l("para el cobro a la salida")
        buf += b'\n' * 5
        buf += CUT_FULL

        return self._enviar_raw(bytes(buf))

    # ─── Ticket de cobro (salida) optimizado ──────────────────────────────────

    def imprimir_cobro(self, sesion: Dict, nombre_negocio: str = "PARKING",
                       tarifa_hora: float = 2.0, moneda: str = "S/",
                       direccion: str = "", telefono: str = "") -> bool:

        entrada = datetime.strptime(sesion["hora_entrada"], "%Y-%m-%d %H:%M:%S")
        salida  = datetime.strptime(sesion["hora_salida"],  "%Y-%m-%d %H:%M:%S")

        minutos   = sesion.get("minutos_total", 0)
        horas_str = f"{minutos // 60}h {minutos % 60:02d}min"
        monto_str = f"{moneda} {sesion['monto']:.2f}"

        buf = bytearray()
        buf += INIT
        buf += CUT_FULL
        buf += b'\n' * 2

        buf += ALIGN_CENTER
        buf += BOLD_ON + TXT_DOUBLE
        buf += self._l(f"  {nombre_negocio}  ")
        buf += BOLD_OFF + TXT_NORMAL
        
        # Parámetros condicionales de la captura (Excluyendo RUC por completo)
        if direccion.strip():
            buf += self._l(direccion.strip())
        if telefono.strip():
            buf += self._l(f"Tel: {telefono.strip()}")
            
        buf += self._sep2()

        buf += ALIGN_LEFT
        buf += self._par("Ticket N°:", sesion["ticket_numero"])
        buf += self._par("Fecha:",     salida.strftime("%d/%m/%Y"))
        buf += self._sep()
        buf += self._par("Vehiculo:", sesion["tipo_vehiculo"])
        buf += self._par("Placa:", sesion["placa"])
        buf += self._sep()
        buf += self._par("Entrada:", entrada.strftime("%I:%M %p"))
        buf += self._par("Salida:",  salida.strftime("%I:%M %p"))
        buf += self._par("Tiempo:",  horas_str)
        buf += self._par("Tarifa:", f"{moneda}{tarifa_hora:.2f}/hr")
        buf += self._sep2()

        buf += ALIGN_CENTER
        buf += BOLD_ON + TXT_DOUBLE
        buf += self._l(f"TOTAL: {monto_str}")
        buf += BOLD_OFF + TXT_NORMAL
        buf += self._sep()
        buf += self._l("*** GRACIAS POR SU VISITA ***")
        buf += b'\n' * 6
        buf += CUT_FULL

        return self._enviar_raw(bytes(buf))