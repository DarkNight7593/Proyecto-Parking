"""
ParkingPro - Instalador y detector de impresoras
Detecta ticketeras instaladas y hardware USB sin driver.
Compatible: Windows 10/11.  En Linux/Mac funciona en modo simulación.
"""
import os
import subprocess
import sys
import threading
import tempfile
import time
from typing import List, Tuple, Dict, Callable, Optional

WINDOWS = (os.name == "nt")

try:
    import win32print
except ImportError:
    win32print = None  # type: ignore

# ─── Constantes ───────────────────────────────────────────────────────────────
DRIVER_NOMBRE = "Generic / Text Only"
DRIVER_INF    = r"%windir%\inf\ntprint.inf"

# Drivers considerados compatibles con impresoras térmicas ESC/POS
GENERIC_DRIVERS = [
    "generic / text only",
    "generic text only",
    "generic",
    "esc/pos",
    "escpos",
]

# Palabras clave en nombre de impresora que sugieren ticketera
_KW_TICKET = [
    "pos", "thermal", "receipt", "ticket", "epson tm", "star bsc",
    "xprinter", "xp-", "3nstar", "bixolon", "citizen ct", "sewoo",
    "rongta", "gprinter", "generic text", "pos-d", "hprt", "birch",
    "esc/pos",
]

# Basura USB que no es impresora
_KW_BASURA = [
    "hub", "audio", "bluetooth", "mouse", "keyboard", "teclado",
    "cámara", "camera", "video", "generic usb", "host controller",
    "raíz", "root", "composite",
]


class PrinterInstaller:
    """Gestiona detección e instalación de ticketeras en Windows."""

    def __init__(self, nombre_impresora: str = "TicketeraEstacionamiento"):
        self.nombre_impresora = nombre_impresora

    # ─── Impresoras instaladas ────────────────────────────────────────────────

    def listar_nombres_instalados(self) -> List[str]:
        """Devuelve los nombres de todas las impresoras instaladas en Windows."""
        if not WINDOWS or win32print is None:
            return []
        try:
            flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
            # FIX: nivel 2 (PRINTER_INFO_2) → "pPrinterName" existe.
            # Nivel 1 (PRINTER_INFO_1) usa "pName", no "pPrinterName" →
            # KeyError silenciado por el except → función siempre retornaba [].
            return [p["pPrinterName"] for p in win32print.EnumPrinters(flags, None, 2)]
        except Exception:
            return []

    def impresora_ya_instalada(self) -> bool:
        return self.nombre_impresora in self.listar_nombres_instalados()

    def listar_impresoras_detalle(self) -> List[Dict]:
        """
        Devuelve información detallada de TODAS las impresoras instaladas.
        Cada dict: {nombre, driver, puerto, es_compatible_termica, es_ticketera}
        Las impresoras con driver Generic/Text Only aparecen primero.
        """
        if not WINDOWS or win32print is None:
            return []
        try:
            flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
            printers = win32print.EnumPrinters(flags, None, 2)
        except Exception:
            return []

        result = []
        for p in printers:
            nombre = p.get("pPrinterName", "")
            driver = p.get("pDriverName", "")
            puerto = p.get("pPortName", "?")
            driver_l = driver.lower()
            nombre_l = nombre.lower()
            es_compatible = any(g in driver_l for g in GENERIC_DRIVERS)
            es_ticketera  = es_compatible or any(k in nombre_l for k in _KW_TICKET)
            result.append({
                "nombre":               nombre,
                "driver":               driver,
                "puerto":               puerto,
                "es_compatible_termica": es_compatible,
                "es_ticketera":          es_ticketera,
            })

        # Orden: compatibles térmicas primero, luego alphabético
        result.sort(key=lambda x: (not x["es_compatible_termica"], x["nombre"].lower()))
        return result

    # ─── Detección de hardware USB sin driver ─────────────────────────────────

    def listar_hardware_sin_driver(self) -> List[Dict]:
        """
        Detecta dispositivos físicos USB de impresión que NO tienen driver instalado.
        Devuelve lista de dicts: {nombre, tipo='hw_detectado'}
        """
        if not WINDOWS:
            return []

        nombres_ya = {d.lower() for d in self.listar_nombres_instalados()}
        encontrados: List[Dict] = []

        try:
            import csv, io
            cmd = [
                "powershell", "-NoProfile", "-Command",
                "Get-PnpDevice -PresentOnly | "
                "Select-Object FriendlyName, InstanceId, Class | "
                "ConvertTo-Csv -NoTypeInformation",
            ]
            res = subprocess.run(cmd, capture_output=True, text=True,
                                 errors="ignore", timeout=20)
            reader = csv.reader(io.StringIO(res.stdout))
            next(reader, None)  # saltar cabecera

            for row in reader:
                if len(row) < 3:
                    continue
                nombre = row[0].strip()
                dev_id = row[1].strip().upper()
                clase  = row[2].strip().upper()

                if not nombre or nombre.lower() in ("unknown", ""):
                    continue
                if any(b in nombre.lower() for b in _KW_BASURA):
                    continue

                es_imp = ("USBPRINT" in dev_id or "PRINTER" in clase or
                          any(k in nombre.lower() for k in ["star", "bsc", "pos", "thermal", "receipt"]))

                if es_imp and nombre.lower() not in nombres_ya:
                    encontrados.append({
                        "nombre":       nombre,
                        "tipo":         "hw_detectado",
                        "es_ticketera": True,
                    })
        except Exception:
            pass

        return encontrados

    # ─── Detección de puerto ──────────────────────────────────────────────────

    def detectar_puerto(self, log: Callable = None) -> str:
        """Detecta el puerto USB más probable para una nueva ticketera."""
        if not WINDOWS:
            return "USB001"

        def _log(m):
            if log:
                log(m)

        _log("🔍 Detectando puerto USB...")

        try:
            cmd = (
                'wmic path win32_pnpentity '
                'where "Service=\'usbprint\' '
                'or Caption like \'%POS%\' '
                'or Caption like \'%Thermal%\' '
                'or Caption like \'%Receipt%\'"'
                ' get Caption,DeviceID /format:list'
            )
            res = subprocess.run(cmd, shell=True, capture_output=True,
                                 text=True, errors="ignore", timeout=10)
            for line in res.stdout.splitlines():
                line = line.strip()
                if line.upper().startswith("DEVICEID="):
                    dev = line.split("=", 1)[1].strip().upper()
                    if "USB" in dev:
                        try:
                            idx = int(dev.split("\\")[-1]) + 1
                            puerto = f"USB{idx:03d}"
                            _log(f"➔ Puerto detectado: {puerto}")
                            return puerto
                        except ValueError:
                            pass
        except Exception:
            pass

        _log("➔ Usando puerto por defecto: USB001")
        return "USB001"

    # ─── Instalación ──────────────────────────────────────────────────────────

    def instalar(self, puerto: str = "USB001",
                 log: Callable = None) -> Tuple[bool, str]:
        """
        Instala la impresora con Generic/Text Only en el puerto indicado.
        Requiere permisos de administrador.
        """
        if not WINDOWS:
            return False, "Solo disponible en Windows."

        if self.impresora_ya_instalada():
            return True, f"'{self.nombre_impresora}' ya está instalada."

        def _log(m):
            if log:
                log(m)

        # Método 1: printui.dll
        try:
            _log("Intentando con printui.dll...")
            cmd = [
                "rundll32", "printui.dll,PrintUIEntry",
                "/if",
                "/b", self.nombre_impresora,
                "/f", os.path.expandvars(DRIVER_INF),
                "/r", puerto,
                "/m", DRIVER_NOMBRE,
            ]
            subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if self.impresora_ya_instalada():
                _log("✅ Instalada con printui.dll")
                return True, f"'{self.nombre_impresora}' instalada en {puerto}."
        except Exception as e:
            _log(f"printui.dll falló: {e}")

        # Método 2: PowerShell
        try:
            _log("Intentando con PowerShell...")
            ps = (
                f'Add-PrinterPort -Name "{puerto}" -ErrorAction SilentlyContinue; '
                f'Add-PrinterDriver -Name "{DRIVER_NOMBRE}" -ErrorAction SilentlyContinue; '
                f'Add-Printer -Name "{self.nombre_impresora}" '
                f'-DriverName "{DRIVER_NOMBRE}" -PortName "{puerto}"'
            )
            subprocess.run(["powershell", "-Command", ps],
                           capture_output=True, text=True, timeout=30)
            if self.impresora_ya_instalada():
                _log("✅ Instalada con PowerShell")
                return True, f"'{self.nombre_impresora}' instalada en {puerto}."
        except Exception as e:
            _log(f"PowerShell falló: {e}")

        return False, (
            "No se pudo instalar automáticamente.\n"
            "Instalación manual:\n"
            "1. Panel de Control → Dispositivos e Impresoras\n"
            "2. Agregar impresora → No en la lista\n"
            f"3. Puerto local → {puerto}\n"
            "4. Driver: Generic / Text Only\n"
            f"5. Nombre: {self.nombre_impresora}"
        )

    def instalar_como_admin(self, nombre_modelo: str,
                             log: Callable = None) -> bool:
        """
        Instala driver Generic/Text Only para el hardware indicado
        solicitando permisos de Administrador via UAC.

        Bloquea hasta que la instalación termine o venza el timeout (120 s).

        Correcciones respecto a la versión anterior:
        - FIX 1: Eliminado CREATE_NO_WINDOW: ese flag suprimía el diálogo UAC.
        - FIX 2: Añadido -Wait a Start-Process: el proceso externo ahora espera
                 a que el proceso elevado termine antes de retornar, evitando
                 que el polling comience antes de que la instalación arranque.
        - FIX 3: Timeout aumentado a 120 s: Add-Printer puede tardar más de
                 21 s en sistemas lentos o con drivers nuevos.
        """
        if not WINDOWS:
            return False

        def _log(m):
            if log:
                log(m)

        _log(f"Preparando script de instalación para: {nombre_modelo}...")

        fd, ps1 = tempfile.mkstemp(suffix=".ps1")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write('Add-PrinterPort -Name "USB001" -ErrorAction SilentlyContinue\n')
                f.write(f'Add-PrinterDriver -Name "{DRIVER_NOMBRE}" -ErrorAction SilentlyContinue\n')
                f.write(
                    f'Add-Printer -Name "{nombre_modelo}" '
                    f'-DriverName "{DRIVER_NOMBRE}" -PortName "USB001" '
                    f'-ErrorAction SilentlyContinue\n'
                )

            _log("Solicitando permisos de Administrador (Windows UAC)...")
            _log("Acepta la ventana UAC que aparecerá en pantalla...")

            # FIX 1: Sin creationflags=CREATE_NO_WINDOW → UAC puede mostrarse.
            # FIX 2: -Wait en Start-Process → subprocess.run bloquea hasta que
            #        el proceso elevado termine (en lugar de retornar al instante).
            # Usamos array PS para evitar problemas de escape con rutas con espacios.
            ps1_safe = ps1.replace("'", "''")  # escapar comilla simple en la ruta
            launch_cmd = (
                f"$a = @('-NoProfile','-ExecutionPolicy','Bypass','-File','{ps1_safe}');"
                f"Start-Process powershell -ArgumentList $a -Verb RunAs -Wait"
            )
            # FIX 3: timeout=120 s → tiempo suficiente para UAC + Add-Printer.
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", launch_cmd],
                timeout=120,
            )

            # Verificar con reintentos: Windows puede tardar un momento
            # en propagar la impresora al registro tras Add-Printer.
            inst_temp = PrinterInstaller(nombre_modelo)
            for intento in range(6):          # hasta ~3 s de espera extra
                if nombre_modelo in inst_temp.listar_nombres_instalados():
                    _log(f"✅ '{nombre_modelo}' instalada correctamente.")
                    return True
                if intento < 5:
                    time.sleep(0.5)

            _log("❌ No se pudo instalar. ¿Rechazaste el permiso de Administrador?")
            return False

        except subprocess.TimeoutExpired:
            _log("❌ Tiempo agotado (120 s). Verifica que aceptaste el UAC.")
            return False
        except Exception as e:
            _log(f"Error: {e}")
            return False

        finally:
            def _borrar():
                time.sleep(5)
                try:
                    os.remove(ps1)
                except Exception:
                    pass
            threading.Thread(target=_borrar, daemon=True).start()

    def instalar_auto(self, log: Callable = None) -> Tuple[bool, str]:
        """Detecta puerto automáticamente e instala la impresora."""
        if not WINDOWS:
            return False, "Solo disponible en Windows."
        if self.impresora_ya_instalada():
            if log:
                log(f"✅ '{self.nombre_impresora}' ya está instalada.")
            return True, "La impresora ya estaba instalada."

        puerto = self.detectar_puerto(log=log) or "USB001"
        return self.instalar(puerto, log=log)

    def eliminar(self) -> Tuple[bool, str]:
        """Elimina la impresora del sistema."""
        if not WINDOWS:
            return False, "Solo en Windows."
        try:
            subprocess.run(
                ["rundll32", "printui.dll,PrintUIEntry",
                 "/dl", "/n", self.nombre_impresora, "/q"],
                timeout=15, capture_output=True,
            )
            return True, f"'{self.nombre_impresora}' eliminada."
        except Exception as e:
            return False, str(e)

    def imprimir_pagina_prueba(self) -> Tuple[bool, str]:
        """Envía una página de prueba a la impresora."""
        if not WINDOWS or win32print is None:
            return False, "Solo en Windows."
        if not self.impresora_ya_instalada():
            return False, "Impresora no instalada."
        try:
            h = win32print.OpenPrinter(self.nombre_impresora)
            win32print.StartDocPrinter(h, 1, ("Test ParkingPro", None, "RAW"))
            win32print.StartPagePrinter(h)
            win32print.WritePrinter(h, b"\x1b@TEST DE IMPRESORA PARKINGPRO\n\n\n\n\n\x1bi")
            win32print.EndPagePrinter(h)
            win32print.EndDocPrinter(h)
            win32print.ClosePrinter(h)
            return True, "Página de prueba enviada."
        except Exception as e:
            return False, str(e)