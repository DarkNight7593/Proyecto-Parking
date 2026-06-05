"""
ParkingPro - Módulo de impresión ESC/POS
Compatible con ticketeras via win32print (Windows).
En sistemas no-Windows funciona en modo simulación (print en consola).

Detección de estado usa WMIC (Win32_Printer) para capturar desconexiones USB
en tiempo real, mucho más fiable que el Status del spooler de Windows.
"""
import os
import subprocess
from datetime import datetime
from typing import Dict

try:
    import win32print
    WINDOWS_PRINT = True
except ImportError:
    WINDOWS_PRINT = False

# ─── Evitar ventana de consola al llamar WMIC ─────────────────────────────────
_CREATE_NO_WINDOW = 0x08000000

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

# ─── WMI PrinterStatus codes ─────────────────────────────────────────────────
# Ref: CIM_Printer.PrinterStatus (Win32_Printer)
_WMI_PRINTER_STATUS = {
    1: ("warning", "⚠ Estado desconocido"),
    2: ("warning", "⚠ Estado no disponible"),
    3: ("ok",      "✓ Lista para imprimir"),
    4: ("ok",      "🖨 Imprimiendo..."),
    5: ("ok",      "⚙ Calentando..."),
    6: ("error",   "⚠ Impresión detenida"),
    7: ("offline", "✗ Desconectada / Offline"),
}

# ─── WMI DetectedErrorState codes ────────────────────────────────────────────
# Ref: CIM_Printer.DetectedErrorState
_WMI_ERROR_STATE = {
    3:  ("warning", "⚠ Papel bajo"),
    4:  ("error",   "⚠ Sin papel"),
    5:  ("warning", "⚠ Tóner/tinta bajo"),
    6:  ("error",   "⚠ Sin tóner/tinta"),
    7:  ("error",   "⚠ Cubierta abierta"),
    8:  ("error",   "⚠ Papel atascado"),
    9:  ("offline", "✗ Desconectada / Offline"),
    10: ("warning", "⚠ Requiere servicio"),
    11: ("error",   "⚠ Bandeja de salida llena"),
}

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

    La detección de estado usa WMIC (Win32_Printer) como fuente primaria,
    con win32print como fallback. WMIC refleja la desconexión USB en segundos,
    mientras que el spooler de Windows puede tardar minutos en actualizarse.
    """

    def __init__(self, nombre_impresora: str):
        self.nombre_impresora = nombre_impresora

    # ─── WMI via WMIC (detección tiempo real) ────────────────────────────────

    def _get_wmi_printer_info(self) -> dict:
        """
        Consulta Win32_Printer via WMIC para obtener estado real del hardware.
        Detecta desconexión USB típicamente en 2-10 segundos.
        Retorna dict con claves: printer_status, detected_error, work_offline.
        Retorna {} si falla o el sistema no es Windows.
        """
        if not WINDOWS_PRINT:
            return {}
        try:
            # Sanear nombre: eliminar comillas
            safe = self.nombre_impresora.replace('"', '').replace("'", "")
            result = subprocess.run(
                [
                    "wmic", "printer",
                    "where", f'Name="{safe}"',
                    "get",
                    "PrinterStatus,DetectedErrorState,WorkOffline",
                    "/format:value",
                ],
                capture_output=True, text=True, timeout=4,
                creationflags=_CREATE_NO_WINDOW,
            )
            data: dict = {}
            for line in result.stdout.split("\n"):
                line = line.strip()
                if "=" in line:
                    k, v = line.split("=", 1)
                    data[k.strip().lower()] = v.strip()

            if not data:
                return {}

            ps_raw = data.get("printerstatus", "")
            de_raw = data.get("detectederrorstate", "")
            wo_raw = data.get("workoffline", "")

            return {
                "printer_status": int(ps_raw) if ps_raw.isdigit() else 3,
                "detected_error": int(de_raw) if de_raw.isdigit() else 0,
                "work_offline":   wo_raw.upper() == "TRUE",
            }
        except Exception:
            return {}

    # ─── Estado ──────────────────────────────────────────────────────────────

    def esta_disponible(self) -> bool:
        """Verifica si la impresora existe en el sistema Windows."""
        if not WINDOWS_PRINT:
            return False
        try:
            flags  = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
            nombres = [p["pPrinterName"] for p in win32print.EnumPrinters(flags, None, 2)]
            return self.nombre_impresora in nombres
        except Exception:
            return False

    def get_estado_detallado(self) -> dict:
        """
        Retorna el estado REAL de la impresora combinando WMI (fuente primaria)
        y win32print (fallback).

        Algoritmo:
          1. Si la impresora no está instalada → offline.
          2. WMI (WMIC) — detecta desconexión USB, sin papel, atascos, etc.
          3. win32print GetPrinter — fallback con flags de Status/Attributes.

        Retorna dict:
          disponible (bool)  — impresora instalada en Windows
          ok         (bool)  — sin errores bloqueantes
          mensaje    (str)   — texto breve para mostrar al usuario
          nivel      (str)   — 'ok' | 'warning' | 'error' | 'offline'
        """
        result = {
            "disponible": False,
            "ok":         False,
            "mensaje":    "",
            "nivel":      "offline",
        }

        if not WINDOWS_PRINT:
            result["mensaje"] = "Simulación (no-Windows)"
            return result

        # 1. ¿Está instalada?
        if not self.esta_disponible():
            result["mensaje"] = f"✗ No instalada: {self.nombre_impresora}"
            return result

        result["disponible"] = True

        # 2. WMI (WMIC) — fuente más fiable para hardware real
        wmi = self._get_wmi_printer_info()
        if wmi:
            work_offline   = wmi.get("work_offline", False)
            printer_status = wmi.get("printer_status", 3)
            detected_error = wmi.get("detected_error", 0)

            # WorkOffline o PrinterStatus=7 → definitivamente desconectada
            if work_offline or printer_status == 7:
                result.update({
                    "ok":      False,
                    "mensaje": "✗ Desconectada / Sin encender",
                    "nivel":   "offline",
                })
                return result

            # DetectedErrorState=9 → offline reportado por dispositivo
            if detected_error == 9:
                result.update({
                    "ok":      False,
                    "mensaje": "✗ Desconectada / Sin encender",
                    "nivel":   "offline",
                })
                return result

            # PrinterStatus=6 → impresión detenida / error
            if printer_status == 6:
                result.update({
                    "ok":      False,
                    "mensaje": "⚠ Impresión detenida / Error",
                    "nivel":   "error",
                })
                return result

            # DetectedErrorState con error/warning conocido
            if detected_error in _WMI_ERROR_STATE:
                nivel, msg = _WMI_ERROR_STATE[detected_error]
                result.update({
                    "ok":      (nivel == "ok"),
                    "mensaje": msg,
                    "nivel":   nivel,
                })
                return result

            # PrinterStatus conocido y positivo
            if printer_status in _WMI_PRINTER_STATUS:
                nivel, msg = _WMI_PRINTER_STATUS[printer_status]
                result.update({
                    "ok":      (nivel == "ok"),
                    "mensaje": msg,
                    "nivel":   nivel,
                })
                return result

            # WMI disponible pero status desconocido → asumir OK
            result.update({
                "ok":      True,
                "mensaje": "✓ Lista para imprimir",
                "nivel":   "ok",
            })
            return result

        # 3. Fallback: win32print GetPrinter
        try:
            h = win32print.OpenPrinter(self.nombre_impresora)
            try:
                info   = win32print.GetPrinter(h, 2)
                status = info.get("Status", 0)
                attrs  = info.get("Attributes", 0)
            finally:
                win32print.ClosePrinter(h)

            # Atributo WorkOffline activo en spooler
            if attrs & _ATTR_WORK_OFFLINE:
                result.update({
                    "ok":      False,
                    "mensaje": "✗ Configurada sin conexión",
                    "nivel":   "offline",
                })
                return result

            # Status=0 → lista
            if status == 0:
                result.update({
                    "ok":      True,
                    "mensaje": "✓ Lista para imprimir",
                    "nivel":   "ok",
                })
                return result

            for flag, nivel, desc in _STATUS_MAP:
                if status & flag:
                    result.update({
                        "ok":      (nivel == "ok"),
                        "mensaje": desc,
                        "nivel":   nivel,
                    })
                    return result

            result.update({
                "ok":      True,
                "mensaje": f"✓ Conectada (0x{status:04X})",
                "nivel":   "ok",
            })

        except Exception as e:
            result.update({
                "ok":      False,
                "mensaje": f"⚠ Error: {e}",
                "nivel":   "warning",
            })

        return result

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
        return (texto[:ANCHO_TICKET] + "\n").encode("latin-1", errors="replace")

    def _sep(self, char: str = "─") -> bytes:
        return self._l(char * ANCHO_TICKET)

    def _sep2(self) -> bytes:
        return self._l("═" * ANCHO_TICKET)

    def _centro(self, texto: str) -> bytes:
        return ALIGN_CENTER + self._l(texto)

    def _par(self, izq: str, der: str) -> bytes:
        espacio = max(1, ANCHO_TICKET - len(izq) - len(der))
        return ALIGN_LEFT + self._l(izq + " " * espacio + der)

    # ─── Ticket de entrada ────────────────────────────────────────────────────

    def imprimir_entrada(self, sesion: Dict, nombre_negocio: str = "PARKING",
                         moneda: str = "S/") -> bool:
        # Verificar estado antes de encolar — no enviar si offline/error
        estado = self.get_estado_detallado()
        if estado["nivel"] in ("error", "offline"):
            print(f"[Impresora] Ticket entrada omitido: {estado['mensaje']}")
            return False

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
        # Verificar estado antes de encolar — no enviar si offline/error
        estado = self.get_estado_detallado()
        if estado["nivel"] in ("error", "offline"):
            print(f"[Impresora] Ticket cobro omitido: {estado['mensaje']}")
            return False

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