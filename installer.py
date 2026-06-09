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
            flags    = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
            printers = win32print.EnumPrinters(flags, None, 2)
        except Exception:
            return []

        result = []
        for p in printers:
            nombre   = p.get("pPrinterName", "")
            driver   = p.get("pDriverName", "")
            puerto   = p.get("pPortName", "?")
            driver_l = driver.lower()
            nombre_l = nombre.lower()
            es_compatible = any(g in driver_l for g in GENERIC_DRIVERS)
            es_ticketera  = es_compatible or any(k in nombre_l for k in _KW_TICKET)
            result.append({
                "nombre":                nombre,
                "driver":                driver,
                "puerto":                puerto,
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

        nombres_ya  = {d.lower() for d in self.listar_nombres_instalados()}
        encontrados: List[Dict] = []

        try:
            import csv, io
            cmd = [
                "powershell", "-NoProfile", "-Command",
                "Get-PnpDevice -PresentOnly | "
                "Select-Object FriendlyName, InstanceId, Class | "
                "ConvertTo-Csv -NoTypeInformation",
            ]
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0

            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                errors="ignore",
                timeout=20,
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
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

                es_imp = (
                    "USBPRINT" in dev_id or "PRINTER" in clase or
                    any(k in nombre.lower() for k in ["star", "bsc", "pos", "thermal", "receipt"])
                )

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
        """
        Detecta el puerto USB exacto del hardware conectado actualmente
        leyendo el Registro de Windows y los dispositivos Plug & Play activos.
        """
        if not WINDOWS:
            return "USB001"

        def _log(m):
            if log:
                log(m)

        _log("🔍 Buscando puerto físico en el Registro de Windows...")

        try:
            # Ampliamos la búsqueda: Cualquier dispositivo PnP 'Presente' (conectado ahora mismo)
            # que tenga 'USB' en su ID (esto cubre tanto 'USB\' como 'USBPRINT\')
            ps_script = (
                "$devs = Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue | "
                "Where-Object { $_.InstanceId -match 'USB' }; "
                "foreach ($d in $devs) { "
                "  $path = 'HKLM:\\SYSTEM\\CurrentControlSet\\Enum\\' + $d.InstanceId + '\\Device Parameters'; "
                "  $p = (Get-ItemProperty -Path $path -Name 'PortName' -ErrorAction SilentlyContinue).PortName; "
                "  if ($p -match '^USB\\d+') { Write-Output $p } "
                "}"
            )

            cmd = ["powershell", "-NoProfile", "-Command", ps_script]
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                errors="ignore",
                timeout=20,
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            # Limpiamos los resultados
            puertos_activos = [
                line.strip() for line in res.stdout.splitlines()
                if line.strip().startswith("USB")
            ]

            if puertos_activos:
                # Si detecta varios puertos activos, tomamos el más alto/reciente
                puertos_activos.sort()
                puerto_real = puertos_activos[-1]
                _log(f"➔ ¡Ticketera encontrada físicamente en el puerto: {puerto_real}!")
                return puerto_real
            else:
                _log("⚠ No se detectó ninguna ticketera conectada y encendida.")

        except Exception as e:
            _log(f"⚠ Error en detección avanzada: {e}")

        _log("➔ Usando puerto por defecto: USB001")
        return "USB001"
  
    # ─── Instalación ──────────────────────────────────────────────────────────

    def instalar_como_admin(self, nombre_modelo: str, puerto: str = "USB001",
                             log: Callable = None) -> bool:
        """
        Instala driver Generic/Text Only para el hardware indicado
        solicitando permisos de Administrador via UAC.
        Bloquea hasta que la instalación termine o venza el timeout (120 s).
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
                f.write(f'Add-PrinterPort -Name "{puerto}" -ErrorAction SilentlyContinue\n')
                f.write(f'Add-PrinterDriver -Name "{DRIVER_NOMBRE}" -ErrorAction SilentlyContinue\n')
                f.write(
                    f'Add-Printer -Name "{nombre_modelo}" '
                    f'-DriverName "{DRIVER_NOMBRE}" -PortName "{puerto}" '
                    f'-ErrorAction SilentlyContinue\n'
                )

            _log("Solicitando permisos de Administrador (Windows UAC)...")
            _log("Acepta la ventana UAC que aparecerá en pantalla...")

            ps1_safe   = ps1.replace("'", "''")
            launch_cmd = (
                f"$a = @('-NoProfile','-ExecutionPolicy','Bypass','-File','{ps1_safe}');"
                f"Start-Process powershell -ArgumentList $a -Verb RunAs -Wait"
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", launch_cmd],
                timeout=120,
            )

            inst_temp = PrinterInstaller(nombre_modelo)
            for intento in range(6):
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

    def reparar_conexion_admin(self, log: Callable = None) -> bool:
        """
        Detecta el nuevo puerto físico USB y actualiza la configuración de Windows.
        Solicita permisos de Administrador (UAC) para asegurar el cambio.
        """
        if not WINDOWS:
            return False

        def _log(m):
            if log:
                log(m)

        _log(f"Buscando nuevo puerto físico para '{self.nombre_impresora}'...")
        
        # 1. Usamos tu detector de alta precisión
        nuevo_puerto = self.detectar_puerto(log=log)
        
        _log(f"➔ Moviendo '{self.nombre_impresora}' al puerto {nuevo_puerto}...")

        fd, ps1 = tempfile.mkstemp(suffix=".ps1")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                # Comando para cambiar solo el puerto de la impresora existente
                f.write(
                    f'Set-Printer -Name "{self.nombre_impresora}" '
                    f'-PortName "{nuevo_puerto}" '
                    f'-ErrorAction Stop\n'
                )

            _log("Solicitando permisos de Administrador (UAC)...")

            ps1_safe   = ps1.replace("'", "''")
            launch_cmd = (
                f"$a = @('-NoProfile','-ExecutionPolicy','Bypass','-File','{ps1_safe}');"
                f"Start-Process powershell -ArgumentList $a -Verb RunAs -Wait"
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", launch_cmd],
                timeout=60,
            )

            # Pequeña pausa para que Windows asimile el cambio
            time.sleep(1)
            return True

        except subprocess.TimeoutExpired:
            _log("❌ Tiempo agotado. ¿Rechazaste el permiso?")
            return False
        except Exception as e:
            _log(f"❌ Error al intentar reparar: {e}")
            return False
        finally:
            def _borrar():
                time.sleep(5)
                try:
                    os.remove(ps1)
                except Exception:
                    pass
            threading.Thread(target=_borrar, daemon=True).start()

    def cambiar_driver_generico(self, nombre_impresora: str,
                                 log: Callable = None) -> bool:
        """
        Cambia el driver de una impresora ya instalada a Generic / Text Only.
        Útil para ticketeras Epson/Star/etc. que tienen su propio driver y no
        responden correctamente a comandos ESC/POS directos.

        Usa UAC (elevación de privilegios) para ejecutar Set-Printer con admin.
        Retorna True si el cambio se verificó correctamente.
        """
        if not WINDOWS:
            return False

        def _log(m):
            if log:
                log(m)

        _log(f"Preparando cambio de driver para '{nombre_impresora}'...")
        _log(f"Driver nuevo: {DRIVER_NOMBRE}")

        fd, ps1 = tempfile.mkstemp(suffix=".ps1")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                # Primero aseguramos que el driver Generic esté disponible
                f.write(
                    f'Add-PrinterDriver -Name "{DRIVER_NOMBRE}" '
                    f'-ErrorAction SilentlyContinue\n'
                )
                # Luego cambiamos el driver de la impresora existente
                f.write(
                    f'Set-Printer -Name "{nombre_impresora}" '
                    f'-DriverName "{DRIVER_NOMBRE}" '
                    f'-ErrorAction Stop\n'
                )

            _log("Solicitando permisos de Administrador (UAC)...")
            _log("Acepta la ventana UAC que aparecerá en pantalla...")

            ps1_safe   = ps1.replace("'", "''")
            launch_cmd = (
                f"$a = @('-NoProfile','-ExecutionPolicy','Bypass','-File','{ps1_safe}');"
                f"Start-Process powershell -ArgumentList $a -Verb RunAs -Wait"
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", launch_cmd],
                timeout=120,
            )

            # Verificar: la impresora debe tener ahora un driver Generic
            time.sleep(1)  # breve pausa para que Windows propague el cambio
            inst_temp = PrinterInstaller(nombre_impresora)
            for intento in range(6):
                detalles = inst_temp.listar_impresoras_detalle()
                for d in detalles:
                    if d["nombre"] == nombre_impresora:
                        if any(g in d["driver"].lower() for g in GENERIC_DRIVERS):
                            _log(f"✅ Driver cambiado correctamente para '{nombre_impresora}'.")
                            return True
                        else:
                            _log(f"⚠ Driver actual: {d['driver']}")
                if intento < 5:
                    time.sleep(0.5)

            _log("❌ No se pudo verificar el cambio. ¿Rechazaste el UAC?")
            return False

        except subprocess.TimeoutExpired:
            _log("❌ Tiempo agotado (120 s).")
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

    def imprimir_pagina_prueba(self) -> Tuple[bool, str]:
        """Envía una página de prueba a la impresora."""
        if not WINDOWS or win32print is None:
            return False, "Solo en Windows."
        if not self.impresora_ya_instalada():
            return False, "Impresora no instalada."
        try:
            h = win32print.OpenPrinter(self.nombre_impresora)
            try:
                win32print.StartDocPrinter(h, 1, ("Test ParkingPro", None, "RAW"))
                win32print.StartPagePrinter(h)
                win32print.WritePrinter(h, b"\x1b@TEST DE IMPRESORA PARKINGPRO\n\n\n\n\n\x1bi")
                win32print.EndPagePrinter(h)
                win32print.EndDocPrinter(h)
            finally:
                win32print.ClosePrinter(h)   # FIX: garantiza cierre aunque WritePrinter falle
            return True, "Página de prueba enviada."
        except Exception as e:
            return False, str(e)