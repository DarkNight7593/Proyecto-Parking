"""
ParkingPro - Módulo de impresión ESC/POS
Compatible con ticketeras via win32print (Windows).
En sistemas no-Windows funciona en modo simulación (print en consola).
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


class Printer:
    """
    Gestiona la comunicación directa con la ticketera via win32print (RAW).
    En no-Windows, simula la salida en consola.
    """

    def __init__(self, nombre_impresora: str):
        self.nombre_impresora = nombre_impresora

    # ─── Estado ──────────────────────────────────────────────────────────────

    def esta_disponible(self) -> bool:
        if not WINDOWS_PRINT:
            return False
        try:
            flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
            nombres = [p[2] for p in win32print.EnumPrinters(flags)]
            return self.nombre_impresora in nombres
        except Exception:
            return False

    def get_estado_texto(self) -> str:
        if not WINDOWS_PRINT:
            return "No disponible (no-Windows)"
        if self.esta_disponible():
            return f"✓ Conectada: {self.nombre_impresora}"
        return f"✗ No encontrada: {self.nombre_impresora}"

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

    # ─── Constructores de líneas ──────────────────────────────────────────────

    def _l(self, texto: str = "") -> bytes:
        """Línea simple con LF, encodada en latin-1."""
        return (texto[:ANCHO_TICKET] + "\n").encode("latin-1", errors="replace")

    def _sep(self, char: str = "─") -> bytes:
        return self._l(char * ANCHO_TICKET)

    def _sep2(self) -> bytes:
        return self._l("═" * ANCHO_TICKET)

    def _centro(self, texto: str) -> bytes:
        return ALIGN_CENTER + self._l(texto)

    def _par(self, izq: str, der: str) -> bytes:
        """Dos columnas: izquierda y derecha."""
        espacio = max(1, ANCHO_TICKET - len(izq) - len(der))
        return ALIGN_LEFT + self._l(izq + " " * espacio + der)

    # ─── Ticket de entrada ────────────────────────────────────────────────────

    def imprimir_entrada(self, sesion: Dict, nombre_negocio: str = "PARKING",
                         moneda: str = "S/") -> bool:
        ahora = datetime.strptime(sesion["hora_entrada"], "%Y-%m-%d %H:%M:%S")

        buf = bytearray()
        buf += INIT
        buf += CUT_FULL
        buf += b'\n' * 2

        buf += ALIGN_CENTER
        buf += BOLD_ON + TXT_DOUBLE
        buf += self._l(f"  {nombre_negocio}  ")
        buf += BOLD_OFF + TXT_NORMAL
        buf += self._l("  Estacionamiento  ")
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

    # ─── Ticket de cobro (salida) ─────────────────────────────────────────────

    def imprimir_cobro(self, sesion: Dict, nombre_negocio: str = "PARKING",
                       tarifa_hora: float = 2.0, moneda: str = "S/") -> bool:
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

    # ─── Cierre de día ────────────────────────────────────────────────────────

    def imprimir_cierre_dia(self, resumen: Dict, nombre_negocio: str = "PARKING",
                            moneda: str = "S/") -> bool:
        ahora = datetime.now()
        buf = bytearray()
        buf += INIT
        buf += CUT_FULL
        buf += b'\n' * 2

        buf += ALIGN_CENTER
        buf += BOLD_ON + TXT_DOUBLE
        buf += self._l("CIERRE DEL DIA")
        buf += TXT_NORMAL
        buf += self._l(nombre_negocio)
        buf += BOLD_OFF
        buf += self._l(ahora.strftime("%d/%m/%Y  %I:%M %p"))
        buf += self._sep2()

        buf += ALIGN_LEFT
        buf += self._par("Total vehiculos:", str(resumen.get("total_vehiculos", 0)))
        buf += self._par("Activos ahora:",   str(resumen.get("activos_ahora", 0)))
        buf += self._par("Promedio tiempo:", f"{int(resumen.get('prom_minutos', 0))} min")
        buf += self._sep()

        buf += ALIGN_CENTER
        buf += BOLD_ON + TXT_DOUBLE
        buf += self._l(f"INGRESOS: {moneda}{resumen.get('ingresos', 0):.2f}")
        buf += BOLD_OFF + TXT_NORMAL
        buf += self._sep2()
        buf += self._l("Impreso por ParkingPro v1.0")
        buf += b'\n' * 5
        buf += CUT_FULL

        return self._enviar_raw(bytes(buf))
