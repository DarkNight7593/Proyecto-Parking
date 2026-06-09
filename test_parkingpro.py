"""
ParkingPro - Suite de Tests de Datos y Exportación
===================================================
Genera datos falsos en una BD temporal y verifica:
  1. Integridad de los métodos de la capa Database
  2. Consistencia de todos los métodos de reporte (get_resumen_rango, etc.)
  3. Exportación Excel (5 hojas) con openpyxl
  4. Coherencia entre los totales de la BD y los valores en el Excel

NO usa impresora, NO usa GUI (sin tkinter/customtkinter/printer).
Crea archivos temporales en /tmp/parkingpro_test/ y los borra al finalizar.

Ejecución: python3 test_parkingpro.py
"""

import os
import sys
import sqlite3
import tempfile
import shutil
import traceback
import configparser
from datetime import datetime, timedelta, date
from typing import List, Dict

# ─── Rutas ─────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# ─── Colores para el output ─────────────────────────────────────────────────────
def _ok(msg):   print(f"  \033[92m✓ {msg}\033[0m")
def _fail(msg): print(f"  \033[91m✗ FALLO: {msg}\033[0m")
def _warn(msg): print(f"  \033[93m⚠ AVISO: {msg}\033[0m")
def _head(msg): print(f"\n\033[1m\033[94m{'='*60}\n  {msg}\n{'='*60}\033[0m")
def _sub(msg):  print(f"\n\033[96m  ── {msg}\033[0m")

ERRORES = []
AVISOS  = []

def check(condition, msg_ok, msg_fail):
    if condition:
        _ok(msg_ok)
    else:
        _fail(msg_fail)
        ERRORES.append(msg_fail)

def warn_check(condition, msg_ok, msg_warn):
    if condition:
        _ok(msg_ok)
    else:
        _warn(msg_warn)
        AVISOS.append(msg_warn)

# ─── Mock de ConfigManager (sin GUI, sin archivo físico requerido) ───────────────
class MockConfig:
    """Reemplaza ConfigManager para los tests sin necesitar config.ini."""
    def get_moneda(self)           -> str:   return "S/"
    def get_nombre_negocio(self)   -> str:   return "Test Parking SA"
    def get_nombre_impresora(self) -> str:   return "TestPrinter"
    def get_tiempo_libre(self)     -> int:   return 0
    def get_tarifa(self, tipo)     -> float: return {"Auto": 2.0, "Moto": 1.5, "Camioneta": 3.0, "Bus": 5.0, "Camión": 5.0, "Bicicleta": 1.0}.get(tipo, 2.0)
    def get_all_tarifas(self)      -> dict:  return {"auto": 2.0, "moto": 1.5, "camioneta": 3.0, "bus": 5.0, "camion": 5.0, "bicicleta": 1.0}
    def get_datos_negocio(self)    -> dict:  return {"nombre": "Test Parking SA", "direccion": "Jr. Test 123", "telefono": "999000111", "ruc": "12345678901"}
    def get_db_path(self)          -> str:   return ":memory:"

# ─── Generador de datos falsos ──────────────────────────────────────────────────
TIPOS = ["Auto", "Moto", "Camioneta", "Bus", "Camión", "Bicicleta"]
PLACAS = [
    "ABC-123", "DEF-456", "GHI-789", "JKL-012", "MNO-345",
    "PQR-678", "STU-901", "VWX-234", "YZA-567", "BCD-890",
    "EFG-111", "HIJ-222", "KLM-333", "NOP-444", "QRS-555",
    "TUV-666", "WXY-777", "ZAB-888", "CDE-999", "FGH-000",
]

def generar_sesiones_falsas(db, ahora: datetime):
    """
    Inserta sesiones en múltiples fechas para poblar todos los períodos.
    Devuelve un dict con los totales esperados para validación posterior.
    """
    sesiones_insertadas = []
    total_ingresos_esperado = 0.0
    total_cobradas_esperado = 0
    total_canceladas_esperado = 0

    # ── Sesiones de los últimos 60 días (1-3 por día, variedad de tipos) ─────
    for dia_atras in range(1, 61):
        fecha_base = ahora - timedelta(days=dia_atras)
        n_sesiones = 1 + (dia_atras % 3)   # 1, 2 o 3 por día

        for j in range(n_sesiones):
            tipo    = TIPOS[(dia_atras + j) % len(TIPOS)]
            placa_i = (dia_atras * 3 + j) % len(PLACAS)
            placa   = PLACAS[placa_i]
            tarifa  = {"Auto": 2.0, "Moto": 1.5, "Camioneta": 3.0, "Bus": 5.0, "Camión": 5.0, "Bicicleta": 1.0}[tipo]

            # Hora de entrada aleatoria entre 08:00 y 18:00
            hora_entrada = fecha_base.replace(
                hour=8 + (dia_atras + j) % 10,
                minute=(dia_atras * 7 + j * 13) % 60,
                second=0, microsecond=0
            )
            # Estadía entre 30 min y 3 horas
            minutos = 30 + ((dia_atras * 5 + j * 17) % 150)
            hora_salida = hora_entrada + timedelta(minutes=minutos)

            # Calcular monto: horas redondeadas hacia arriba
            horas = minutos // 60 + 1
            monto = round(horas * tarifa, 2)

            # ~10% canceladas (días pares, primera sesión)
            cancelar = (dia_atras % 10 == 0 and j == 0)

            ticket = f"TK{hora_entrada.strftime('%Y%m%d')}{(dia_atras*3+j):04d}"

            conn = db._conn()
            conn.execute(
                """INSERT INTO sesiones
                   (ticket_numero, placa, tipo_vehiculo, hora_entrada,
                    hora_salida, minutos_total, monto, estado, observaciones)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ticket,
                    placa,
                    tipo,
                    hora_entrada.strftime("%Y-%m-%d %H:%M:%S"),
                    hora_salida.strftime("%Y-%m-%d %H:%M:%S") if not cancelar else None,
                    minutos if not cancelar else None,
                    monto if not cancelar else None,
                    "cancelado" if cancelar else "cobrado",
                    "",
                )
            )
            conn.commit()

            sesiones_insertadas.append({
                "ticket": ticket,
                "tipo": tipo,
                "fecha": hora_entrada.date().isoformat(),
                "monto": monto if not cancelar else None,
                "estado": "cancelado" if cancelar else "cobrado",
            })

            if not cancelar:
                total_ingresos_esperado += monto
                total_cobradas_esperado += 1
            else:
                total_canceladas_esperado += 1

    # ── Sesiones de HOY (para probar get_ingresos_por_hora) ─────────────────
    for hora in [9, 11, 14, 16]:
        tipo  = TIPOS[hora % len(TIPOS)]
        placa = PLACAS[hora % len(PLACAS)]
        tarifa = {"Auto": 2.0, "Moto": 1.5, "Camioneta": 3.0, "Bus": 5.0, "Camión": 5.0, "Bicicleta": 1.0}[tipo]
        entrada = ahora.replace(hour=hora, minute=0, second=0, microsecond=0)
        salida  = entrada + timedelta(minutes=90)
        minutos = 90
        monto   = round(2 * tarifa, 2)
        ticket  = f"TKHOY{hora:02d}0001"

        conn = db._conn()
        conn.execute(
            """INSERT INTO sesiones
               (ticket_numero, placa, tipo_vehiculo, hora_entrada,
                hora_salida, minutos_total, monto, estado)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'cobrado')""",
            (ticket, placa, tipo,
             entrada.strftime("%Y-%m-%d %H:%M:%S"),
             salida.strftime("%Y-%m-%d %H:%M:%S"),
             minutos, monto)
        )
        conn.commit()
        total_ingresos_esperado += monto
        total_cobradas_esperado += 1

    # ── 2 sesiones ACTIVAS (sin cerrar) ────────────────────────────────────
    for i, (placa, tipo) in enumerate([("ZZZ-001", "Auto"), ("ZZZ-002", "Moto")]):
        ticket  = f"TKACTIVO{i+1:04d}"
        entrada = ahora - timedelta(minutes=45)
        conn = db._conn()
        conn.execute(
            """INSERT INTO sesiones
               (ticket_numero, placa, tipo_vehiculo, hora_entrada, estado)
               VALUES (?, ?, ?, ?, 'activo')""",
            (ticket, placa, tipo, entrada.strftime("%Y-%m-%d %H:%M:%S"))
        )
        conn.commit()

    return {
        "total_cobradas": total_cobradas_esperado,
        "total_canceladas": total_canceladas_esperado,
        "total_ingresos": round(total_ingresos_esperado, 2),
        "sesiones": sesiones_insertadas,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# SUITE DE TESTS
# ═══════════════════════════════════════════════════════════════════════════════

def test_01_database_inicializacion(db):
    _head("TEST 01 – Inicialización de la BD")
    db.inicializar()
    conn = db._conn()
    tablas = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    check("sesiones" in tablas, "Tabla 'sesiones' creada", "Tabla 'sesiones' NO existe")

    indices = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'").fetchall()]
    for idx in ["idx_sesiones_estado", "idx_sesiones_placa",
                "idx_sesiones_entrada", "idx_sesiones_ticket"]:
        check(idx in indices, f"Índice '{idx}' existe", f"Índice '{idx}' FALTA")


def test_02_registro_entrada(db):
    _head("TEST 02 – Registro de Entrada")

    _sub("Registro normal")
    s = db.registrar_entrada("TEST001", "Auto", "obs test")
    check(s["ticket_numero"].startswith("TK"), "Ticket con formato TKyyyymmdd...", "Ticket sin formato correcto")
    check(s["placa"] == "TEST001", "Placa guardada en mayúsculas", "Placa incorrecta")
    check(s["estado"] == "activo", "Estado = 'activo'", "Estado incorrecto")
    check(s["tipo_vehiculo"] == "Auto", "Tipo vehículo correcto", "Tipo incorrecto")
    check(s["hora_entrada"] is not None, "hora_entrada registrada", "hora_entrada NULL")
    check(s["hora_salida"] is None, "hora_salida NULL al inicio", "hora_salida no es NULL")
    check(s["monto"] is None, "monto NULL al inicio", "monto no es NULL")

    _sub("Prevenir placa duplicada activa")
    try:
        db.registrar_entrada("TEST001", "Moto")
        check(False, "", "Debe lanzar ValueError en placa duplicada activa")
    except ValueError as e:
        check(True, f"ValueError correcto al duplicar placa: {e}", "")

    _sub("Placa normalizada a mayúsculas")
    s2 = db.registrar_entrada("lower-abc", "Moto")
    check(s2["placa"] == "LOWER-ABC", "Placa lowercase → UPPER-ABC", "Placa no normalizada")

    # Limpiar las de prueba
    conn = db._conn()
    conn.execute("DELETE FROM sesiones WHERE placa IN ('TEST001','LOWER-ABC')")
    conn.commit()


def test_03_cobrar_sesion(db):
    _head("TEST 03 – Cobro de Sesión")

    s = db.registrar_entrada("COBRO001", "Camioneta")
    sesion_id = s["id"]

    _sub("Cobro normal")
    cobrada = db.cobrar_sesion(sesion_id, 6.0)
    check(cobrada["estado"] == "cobrado", "Estado → 'cobrado'", "Estado no cambió a cobrado")
    check(cobrada["monto"] == 6.0, "Monto guardado = 6.0", f"Monto incorrecto: {cobrada['monto']}")
    check(cobrada["hora_salida"] is not None, "hora_salida registrada", "hora_salida NULL tras cobro")
    check(cobrada["minutos_total"] >= 0, "minutos_total >= 0", "minutos_total negativo")

    _sub("No se puede cobrar una sesión ya cobrada")
    try:
        db.cobrar_sesion(sesion_id, 6.0)
        check(False, "", "Debe lanzar ValueError en doble cobro")
    except ValueError:
        check(True, "ValueError al intentar cobrar sesión ya cobrada", "")

    _sub("No se puede cobrar sesión inexistente")
    try:
        db.cobrar_sesion(999999, 5.0)
        check(False, "", "Debe lanzar ValueError con ID inexistente")
    except ValueError:
        check(True, "ValueError con ID de sesión inexistente", "")

    # Limpiar sesión de prueba para no contaminar los conteos de "Hoy"
    conn = db._conn()
    conn.execute("DELETE FROM sesiones WHERE placa='COBRO001'")
    conn.commit()


def test_04_cancelar_sesion(db):
    _head("TEST 04 – Cancelación de Sesión")

    s = db.registrar_entrada("CANCEL001", "Bus")
    db.cancelar_sesion(s["id"])
    cancelada = db.get_sesion_por_id(s["id"])
    check(cancelada["estado"] == "cancelado", "Estado → 'cancelado'", "Estado no cambió a cancelado")
    check(cancelada["monto"] is None, "monto NULL en cancelada", "monto no NULL en cancelada")
    check(cancelada["hora_salida"] is None, "hora_salida NULL en cancelada", "hora_salida no NULL")

    # Limpiar sesión de prueba
    conn = db._conn()
    conn.execute("DELETE FROM sesiones WHERE placa='CANCEL001'")
    conn.commit()


def test_05_contar_activos(db, esperados_activos: int):
    _head("TEST 05 – Conteo de Activos")
    n = db.contar_activos()
    check(isinstance(n, int), "contar_activos() retorna int", "No es int")
    check(n >= esperados_activos,
          f"Hay al menos {esperados_activos} activos ({n} reales)",
          f"Esperaba ≥{esperados_activos} activos, hay {n}")


def test_06_get_sesiones_activas(db):
    _head("TEST 06 – get_sesiones_activas()")
    activas = db.get_sesiones_activas()
    check(isinstance(activas, list), "Retorna lista", "No es lista")
    for s in activas:
        check(s["estado"] == "activo",
              f"Sesión {s['ticket_numero']} estado='activo'",
              f"Sesión {s['ticket_numero']} tiene estado='{s['estado']}' (debería ser 'activo')")
        check(s["hora_salida"] is None,
              f"hora_salida NULL en activa {s['ticket_numero']}",
              f"hora_salida no NULL en activa {s['ticket_numero']}")


def test_07_get_resumen_rango(db, esperados: dict, ahora: datetime):
    _head("TEST 07 – get_resumen_rango()")

    hoy_str = ahora.date().isoformat()
    año_str = f"{ahora.year}-01-01"
    fin_str = f"{ahora.year}-12-31"

    _sub("Rango de todo el año actual")
    res = db.get_resumen_rango(año_str, fin_str)
    needed_keys = ["total_vehiculos", "cobrados", "cancelados", "activos_ahora",
                   "ingresos", "prom_minutos"]
    for k in needed_keys:
        check(k in res, f"Clave '{k}' presente en resumen", f"Clave '{k}' FALTA")

    check(res["cobrados"] >= 0, "cobrados >= 0", f"cobrados negativo: {res['cobrados']}")
    check(res["cancelados"] >= 0, "cancelados >= 0", f"cancelados negativo: {res['cancelados']}")
    check(float(res["ingresos"]) >= 0, "ingresos >= 0", f"ingresos negativo: {res['ingresos']}")
    check(float(res["prom_minutos"]) >= 0, "prom_minutos >= 0", f"prom negativo")

    _sub("Coherencia: cobrados + cancelados + activos ≤ total_vehiculos")
    total_calc = res["cobrados"] + res["cancelados"] + res["activos_ahora"]
    check(total_calc <= res["total_vehiculos"],
          f"cobr+canc+activ ({total_calc}) ≤ total ({res['total_vehiculos']})",
          f"total_vehiculos incoherente: {total_calc} > {res['total_vehiculos']}")

    _sub("Rango futuro debe dar 0 ingresos")
    res_futuro = db.get_resumen_rango("2099-01-01", "2099-12-31")
    check(float(res_futuro["ingresos"]) == 0.0,
          "Rango futuro da ingresos=0", f"Rango futuro dio ingresos={res_futuro['ingresos']}")

    _sub("Rango 'Hoy' — verifica sesiones del día actual")
    res_hoy = db.get_resumen_rango(hoy_str, hoy_str)
    check(int(res_hoy["cobrados"]) == 4,
          f"Hoy: 4 cobradas (son {res_hoy['cobrados']})",
          f"Hoy: esperaba 4 cobradas, hay {res_hoy['cobrados']}")


def test_08_get_ingresos_por_hora(db, ahora: datetime):
    _head("TEST 08 – get_ingresos_por_hora()")

    hoy = ahora.date().isoformat()
    datos = db.get_ingresos_por_hora(hoy)
    check(isinstance(datos, list), "Retorna lista", "No es lista")

    horas_con_datos = {d["hora"] for d in datos}
    for h in ["09", "11", "14", "16"]:
        check(h in horas_con_datos,
              f"Hora '{h}' presente en resultado",
              f"Hora '{h}' FALTA (tenía sesiones en esa hora)")

    for d in datos:
        check("hora" in d and "vehiculos" in d and "ingresos" in d,
              f"Estructura correcta para hora {d.get('hora','?')}",
              f"Faltan claves en entrada hora: {d}")
        check(float(d["ingresos"]) >= 0,
              f"Hora {d['hora']}: ingresos >= 0",
              f"Hora {d['hora']}: ingresos negativo {d['ingresos']}")

    _sub("Día sin datos → lista vacía")
    sin_datos = db.get_ingresos_por_hora("2000-01-01")
    check(sin_datos == [], "Día sin datos → []", f"Esperaba [], obtuve {sin_datos}")


def test_09_get_ingresos_por_dia(db, ahora: datetime):
    _head("TEST 09 – get_ingresos_por_dia()")

    fi = (ahora - timedelta(days=7)).date().isoformat()
    ff = ahora.date().isoformat()
    datos = db.get_ingresos_por_dia(fi, ff)
    check(isinstance(datos, list), "Retorna lista", "No es lista")

    for d in datos:
        check("fecha" in d and "vehiculos" in d and "ingresos" in d,
              f"Estructura correcta para fecha {d.get('fecha','?')}",
              f"Faltan claves: {d}")
        try:
            date.fromisoformat(d["fecha"])
            check(True, f"fecha '{d['fecha']}' es ISO válida", "")
        except Exception:
            check(False, "", f"fecha '{d['fecha']}' NO es ISO válida")
        check(int(d["vehiculos"]) >= 0, "vehiculos >= 0", f"vehiculos negativos: {d}")
        check(float(d["ingresos"]) >= 0, "ingresos >= 0", f"ingresos negativos: {d}")

    _sub("Todas las fechas están dentro del rango pedido")
    fi_d = date.fromisoformat(fi)
    ff_d = date.fromisoformat(ff)
    for d in datos:
        fd = date.fromisoformat(d["fecha"])
        check(fi_d <= fd <= ff_d,
              f"Fecha {d['fecha']} dentro de rango",
              f"Fecha {d['fecha']} FUERA del rango {fi}..{ff}")


def test_10_get_ingresos_por_mes_en_anio(db, ahora: datetime):
    _head("TEST 10 – get_ingresos_por_mes_en_año()")

    datos = db.get_ingresos_por_mes_en_año(ahora.year)
    check(isinstance(datos, list), "Retorna lista", "No es lista")
    check(len(datos) <= 12, f"Máximo 12 meses ({len(datos)} obtenidos)", "Más de 12 meses devueltos")

    for d in datos:
        check("mes" in d and "vehiculos" in d and "ingresos" in d,
              f"Estructura correcta mes {d.get('mes','?')}",
              f"Faltan claves: {d}")
        mes_num = int(d["mes"])
        check(1 <= mes_num <= 12,
              f"Mes {d['mes']} en rango 01-12",
              f"Mes {d['mes']} FUERA de rango 01-12")

    _sub("Año sin datos → lista vacía")
    datos_viejos = db.get_ingresos_por_mes_en_año(1999)
    check(datos_viejos == [], "Año 1999 → []", f"Esperaba [], obtuve {datos_viejos}")


def test_11_get_por_tipo_rango(db, ahora: datetime):
    _head("TEST 11 – get_por_tipo_rango()")

    fi = (ahora - timedelta(days=30)).date().isoformat()
    ff = ahora.date().isoformat()
    datos = db.get_por_tipo_rango(fi, ff)
    check(isinstance(datos, list), "Retorna lista", "No es lista")

    tipos_esperados = set(TIPOS)
    tipos_obtenidos = {d["tipo_vehiculo"] for d in datos}
    for t in tipos_obtenidos:
        check(t in tipos_esperados,
              f"Tipo '{t}' es válido",
              f"Tipo '{t}' NO está en la lista de tipos válidos")

    # No debe haber sesiones activas en el desglose
    total_cobradas_tipo = sum(int(d["cantidad"]) for d in datos)
    resumen_rango = db.get_resumen_rango(fi, ff)
    check(total_cobradas_tipo == int(resumen_rango["cobrados"]),
          f"Suma por tipo ({total_cobradas_tipo}) = cobrados en resumen ({resumen_rango['cobrados']})",
          f"Discrepancia: suma tipos={total_cobradas_tipo} vs resumen cobrados={resumen_rango['cobrados']}")

    total_ingresos_tipo = round(sum(float(d["ingresos"]) for d in datos), 2)
    ingr_resumen = round(float(resumen_rango["ingresos"]), 2)
    check(abs(total_ingresos_tipo - ingr_resumen) < 0.01,
          f"Ingresos por tipo ({total_ingresos_tipo}) coincide con resumen ({ingr_resumen})",
          f"Discrepancia de ingresos: tipos={total_ingresos_tipo} vs resumen={ingr_resumen}")


def test_12_get_historial_rango(db, ahora: datetime):
    _head("TEST 12 – get_historial_rango()")

    fi = (ahora - timedelta(days=30)).date().isoformat()
    ff = ahora.date().isoformat()
    hist = db.get_historial_rango(fi, ff, limit=10)
    check(isinstance(hist, list), "Retorna lista", "No es lista")
    check(len(hist) <= 10, f"Máximo 10 ítems respetado ({len(hist)})", "Superó el limit=10")

    for s in hist:
        check(s["estado"] != "activo",
              f"Sesión {s['ticket_numero']} no es activa (es {s['estado']})",
              f"Sesión activa en historial: {s['ticket_numero']}")

    _sub("Orden descendente por hora_entrada")
    fechas = [s["hora_entrada"] for s in hist]
    check(fechas == sorted(fechas, reverse=True),
          "Historial ordenado DESC por hora_entrada",
          "Historial NO está ordenado descendente")

    _sub("Ningún registro fuera del rango pedido")
    fi_d = date.fromisoformat(fi)
    ff_d = date.fromisoformat(ff)
    for s in hist:
        fd = date.fromisoformat(s["hora_entrada"][:10])
        check(fi_d <= fd <= ff_d,
              f"Sesión {s['ticket_numero']} dentro del rango",
              f"Sesión {s['ticket_numero']} FUERA del rango")


def test_13_get_totales_globales(db, esperados: dict):
    _head("TEST 13 – get_totales_globales()")

    tot = db.get_totales_globales()
    needed = ["total_sesiones", "canceladas", "total_ingresaron",
              "ingresos_totales", "ticket_maximo"]
    for k in needed:
        check(k in tot, f"Clave '{k}' presente", f"Clave '{k}' FALTA")

    check(int(tot["total_sesiones"]) >= esperados["total_cobradas"],
          f"total_sesiones >= cobradas esperadas ({esperados['total_cobradas']})",
          f"total_sesiones demasiado bajo")

    check(float(tot["ingresos_totales"]) >= esperados["total_ingresos"] - 0.01,
          f"ingresos_totales ≈ esperado (≥{esperados['total_ingresos']:.2f})",
          f"ingresos_totales {tot['ingresos_totales']:.2f} < esperado {esperados['total_ingresos']:.2f}")

    check(float(tot["ticket_maximo"]) > 0,
          f"ticket_maximo > 0 ({tot['ticket_maximo']})",
          "ticket_maximo = 0 (debería haber sesiones cobradas)")

    check(int(tot["total_ingresaron"]) == int(tot["total_sesiones"]) + int(tot["canceladas"]) + db.contar_activos(),
          "total_ingresaron = cobradas + canceladas + activas",
          f"total_ingresaron incoherente: {tot['total_ingresaron']} vs {int(tot['total_sesiones'])+int(tot['canceladas'])+db.contar_activos()}")


def test_14_excel_export(db, config, tmp_dir: str):
    _head("TEST 14 – Exportación a Excel (ExcelExporter)")

    # Importar con el DataPoint corregido ya
    import importlib
    import openpyxl
    from openpyxl.chart.series import DataPoint  # Importación correcta

    try:
        from excel_exporter import ExcelExporter
        _ok("ExcelExporter importado correctamente")
    except ImportError as e:
        _fail(f"No se pudo importar ExcelExporter: {e}")
        ERRORES.append(f"ImportError ExcelExporter: {e}")
        return

    ruta = os.path.join(tmp_dir, "test_reporte.xlsx")
    exporter = ExcelExporter(db, config)

    _sub("Generación del archivo .xlsx")
    try:
        exporter.exportar(ruta)
        check(os.path.exists(ruta), f"Archivo creado en {ruta}", "Archivo NO creado")
    except Exception as e:
        _fail(f"exportar() lanzó excepción: {e}")
        traceback.print_exc()
        ERRORES.append(f"ExcelExporter.exportar() falló: {e}")
        return

    _sub("Verificación de hojas del libro")
    wb = openpyxl.load_workbook(ruta)
    hojas = wb.sheetnames
    print(f"    Hojas encontradas: {hojas}")

    check("Resumen" in hojas, "Hoja 'Resumen' existe", "Hoja 'Resumen' FALTA")
    check("Sesiones" in hojas, "Hoja 'Sesiones' existe", "Hoja 'Sesiones' FALTA")
    check("Mes Actual" in hojas, "Hoja 'Mes Actual' existe", "Hoja 'Mes Actual' FALTA")
    check(len(hojas) == 5, f"Exactamente 5 hojas ({len(hojas)} encontradas)", f"Se esperaban 5 hojas, hay {len(hojas)}")

    _sub("Hoja Sesiones — estructura de columnas")
    ws_ses = wb["Sesiones"]
    headers = [ws_ses.cell(row=2, column=c).value for c in range(1, 11)]
    expected_headers = ["Ticket", "Placa", "Tipo Vehículo",
                        "Fecha Entrada", "Hora Entrada",
                        "Fecha Salida", "Hora Salida",
                        "Duración (min)", f"Monto ({config.get_moneda()})", "Estado"]
    for i, (got, exp) in enumerate(zip(headers, expected_headers), 1):
        check(got == exp,
              f"Col {i} cabecera '{exp}' correcta",
              f"Col {i}: esperaba '{exp}', hay '{got}'")

    _sub("Hoja Sesiones — valores no nulos en filas de datos")
    last_row = ws_ses.max_row
    check(last_row >= 4, f"Hay al menos 1 fila de datos (max_row={last_row})", "Sin filas de datos")

    errores_fila = 0
    for r in range(3, min(last_row, 20)):   # revisar primeras 17 filas
        ticket = ws_ses.cell(row=r, column=1).value
        placa  = ws_ses.cell(row=r, column=2).value
        tipo   = ws_ses.cell(row=r, column=3).value
        estado = ws_ses.cell(row=r, column=10).value

        if ticket == "TOTALES" or ticket is None:
            continue

        if not ticket or not placa or not tipo or not estado:
            errores_fila += 1
            _fail(f"Fila {r}: campos vacíos — ticket={ticket} placa={placa} tipo={tipo} estado={estado}")

        if estado not in ("Cobrado", "Cancelado", "Activo"):
            errores_fila += 1
            _fail(f"Fila {r}: estado inválido '{estado}'")

    check(errores_fila == 0, "Todas las filas de Sesiones tienen datos válidos", f"{errores_fila} fila(s) con problemas en Sesiones")

    _sub("Hoja Sesiones — estado capitalizado (para fórmulas COUNTIF)")
    for r in range(3, min(last_row, 50)):
        estado = ws_ses.cell(row=r, column=10).value
        if estado and estado not in ("Cobrado", "Cancelado", "Totales", "TOTALES"):
            warn_check(False, "",
                f"Estado inesperado en fila {r}: '{estado}' (COUNTIF espera 'Cobrado'/'Cancelado')")

    _sub("Hoja Mes Actual — columnas correctas")
    ws_mes = wb["Mes Actual"]
    mes_headers = [ws_mes.cell(row=2, column=c).value for c in range(1, 5)]
    check(mes_headers[0] == "Fecha",
          f"Col 1 Mes Actual = 'Fecha' ({mes_headers[0]})",
          f"Col 1 Mes Actual = '{mes_headers[0]}' (esperaba 'Fecha')")
    check(mes_headers[1] == "Día",
          f"Col 2 Mes Actual = 'Día' ({mes_headers[1]})",
          f"Col 2 Mes Actual = '{mes_headers[1]}' (esperaba 'Día')")

    _sub("Hoja Mensual — 12 meses + fila TOTAL en fila 15")
    mensual_sheet = [s for s in hojas if s.startswith("Mensual")]
    if mensual_sheet:
        ws_msl = wb[mensual_sheet[0]]
        fila_total = ws_msl.cell(row=15, column=1).value
        check(fila_total == "TOTAL",
              f"Fila 15 de Mensual = 'TOTAL' ({fila_total})",
              f"Fila 15 de Mensual = '{fila_total}' (esperaba 'TOTAL')")

        # Verificar que los 12 meses existen
        meses_en_hoja = [ws_msl.cell(row=r, column=1).value for r in range(3, 15)]
        meses_esperados = ["Enero","Febrero","Marzo","Abril","Mayo","Junio",
                           "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"]
        check(meses_en_hoja == meses_esperados,
              "Los 12 meses están en orden correcto",
              f"Meses incorrectos: {meses_en_hoja}")

    _sub("Hoja Resumen — título y fecha de generación")
    ws_res = wb["Resumen"]
    titulo = ws_res.cell(row=1, column=1).value
    check(titulo is not None and "ParkingPro" in str(titulo),
          f"Título contiene 'ParkingPro': '{titulo}'",
          f"Título incorrecto: '{titulo}'")

    hoja_tipo_sheet = [s for s in hojas if "Tipo" in s or "tipo" in s]
    _sub("Hoja Por Tipo — estructura")
    if hoja_tipo_sheet:
        ws_tipo = wb[hoja_tipo_sheet[0]]
        tipo_h = [ws_tipo.cell(row=2, column=c).value for c in range(1, 6)]
        check("Tipo Vehículo" in tipo_h,
              "Col 'Tipo Vehículo' presente en Por Tipo",
              f"Cabecera Por Tipo inesperada: {tipo_h}")
        check("Cantidad" in tipo_h,
              "Col 'Cantidad' presente en Por Tipo",
              f"Col Cantidad falta: {tipo_h}")

    wb.close()
    _ok("Archivo Excel cerrado sin errores")


def test_15_coherencia_excel_vs_db(db, config, tmp_dir: str):
    _head("TEST 15 – Coherencia Excel ↔ BD (totales)")

    import openpyxl

    ruta = os.path.join(tmp_dir, "test_coherencia.xlsx")
    try:
        from excel_exporter import ExcelExporter
        ExcelExporter(db, config).exportar(ruta)
    except Exception as e:
        _fail(f"No se pudo generar el Excel para coherencia: {e}")
        ERRORES.append(str(e))
        return

    wb = openpyxl.load_workbook(ruta)

    # Totales reales de la BD
    globales = db.get_totales_globales()
    db_cobradas = int(globales["total_sesiones"])

    # Totales en hoja Sesiones (contar filas cobradas excluyendo TOTALES)
    ws_ses = wb["Sesiones"]
    excel_cobradas = 0
    excel_ingresos = 0.0
    for r in range(3, ws_ses.max_row + 1):
        estado = ws_ses.cell(row=r, column=10).value
        monto  = ws_ses.cell(row=r, column=9).value
        if estado == "Cobrado":
            excel_cobradas += 1
            if isinstance(monto, (int, float)):
                excel_ingresos += float(monto)

    check(excel_cobradas == db_cobradas,
          f"Sesiones cobradas: Excel({excel_cobradas}) = BD({db_cobradas})",
          f"DISCREPANCIA: Excel tiene {excel_cobradas} cobradas, BD tiene {db_cobradas}")

    db_ingresos = round(float(globales["ingresos_totales"]), 2)
    excel_ingresos_r = round(excel_ingresos, 2)
    check(abs(db_ingresos - excel_ingresos_r) < 0.02,
          f"Ingresos totales: Excel({excel_ingresos_r}) ≈ BD({db_ingresos})",
          f"DISCREPANCIA de ingresos: Excel={excel_ingresos_r} vs BD={db_ingresos}")

    _sub("La fila TOTAL de Sesiones es correcta")
    last = ws_ses.max_row
    total_cel = ws_ses.cell(row=last, column=1).value
    total_monto_cel = ws_ses.cell(row=last, column=9).value

    warn_check(total_cel == "TOTALES",
               f"Fila final de Sesiones = 'TOTALES' ({total_cel})",
               f"Fila final de Sesiones = '{total_cel}' (esperaba 'TOTALES')")

    if isinstance(total_monto_cel, (int, float)):
        check(abs(float(total_monto_cel) - excel_ingresos_r) < 0.02,
              f"Monto TOTALES ({total_monto_cel:.2f}) coincide con suma manual ({excel_ingresos_r:.2f})",
              f"Monto TOTALES ({total_monto_cel:.2f}) ≠ suma manual ({excel_ingresos_r:.2f})")

    wb.close()


def test_16_edge_cases(db, tmp_dir: str):
    _head("TEST 16 – Casos Borde")

    _sub("Rango sin datos (mes futuro)")
    res = db.get_resumen_rango("2099-06-01", "2099-06-30")
    check(float(res.get("ingresos", 0)) == 0.0, "Rango futuro → ingresos=0", "ingresos≠0 en rango futuro")
    check(int(res.get("cobrados", 0)) == 0, "Rango futuro → cobrados=0", "cobrados≠0 en rango futuro")

    _sub("get_historial_rango con limit=0")
    hist = db.get_historial_rango("2020-01-01", "2099-12-31", limit=0)
    check(hist == [], "limit=0 → []", f"limit=0 devolvió {len(hist)} items")

    _sub("get_por_tipo_rango en rango sin cobradas")
    tipos = db.get_por_tipo_rango("2099-01-01", "2099-12-31")
    check(tipos == [], "Rango sin cobradas → []", f"Esperaba [], obtuve {tipos}")

    _sub("get_sesion_por_id con ID inexistente")
    s = db.get_sesion_por_id(999999999)
    check(s is None, "ID inexistente → None", f"Esperaba None, obtuve {s}")

    _sub("get_sesion_activa_por_placa con placa no activa")
    s2 = db.get_sesion_activa_por_placa("PLACA_FALSA_XYZ")
    check(s2 is None, "Placa no activa → None", f"Esperaba None, obtuve {s2}")


def test_17_integridad_tipos_en_excel(db, config, tmp_dir: str):
    _head("TEST 17 – Tipos de datos en Excel (no strings donde van números)")

    import openpyxl
    ruta = os.path.join(tmp_dir, "test_tipos.xlsx")
    try:
        from excel_exporter import ExcelExporter
        ExcelExporter(db, config).exportar(ruta)
    except Exception as e:
        _fail(f"Exportación fallida: {e}")
        return

    wb = openpyxl.load_workbook(ruta)
    ws = wb["Sesiones"]

    errores_tipo = []
    for r in range(3, ws.max_row):
        ticket = ws.cell(row=r, column=1).value
        if ticket in (None, "TOTALES"):
            continue
        estado = ws.cell(row=r, column=10).value
        if estado != "Cobrado":
            continue
        # Col 8: duración (debe ser int o "—")
        dur = ws.cell(row=r, column=8).value
        if dur != "—" and not isinstance(dur, (int, float)):
            errores_tipo.append(f"Fila {r} col 8 (duración): tipo {type(dur)} valor '{dur}'")
        # Col 9: monto (debe ser float o "—")
        monto = ws.cell(row=r, column=9).value
        if monto != "—" and not isinstance(monto, (int, float)):
            errores_tipo.append(f"Fila {r} col 9 (monto): tipo {type(monto)} valor '{monto}'")

    check(len(errores_tipo) == 0,
          "Todos los campos numéricos son int/float en Sesiones",
          f"{len(errores_tipo)} error(es) de tipo:\n" + "\n".join(errores_tipo[:5]))

    # Mensual: vehículos deben ser int, ingresos float
    mensual_sheets = [s for s in wb.sheetnames if s.startswith("Mensual")]
    if mensual_sheets:
        ws_m = wb[mensual_sheets[0]]
        for r in range(3, 15):
            veh = ws_m.cell(row=r, column=2).value
            ing = ws_m.cell(row=r, column=3).value
            if not isinstance(veh, (int, type(None))):
                check(False, "", f"Mensual fila {r} col 2 (veh): tipo {type(veh)}, valor '{veh}'")
            if not isinstance(ing, (float, int, type(None))):
                check(False, "", f"Mensual fila {r} col 3 (ing): tipo {type(ing)}, valor '{ing}'")
        _ok("Tipos numéricos en hoja Mensual correctos")

    wb.close()


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print("\n" + "="*60)
    print("  ParkingPro – Suite de Tests de Datos y Exportación")
    print("="*60)

    # Directorio temporal
    tmp_dir = tempfile.mkdtemp(prefix="parkingpro_test_")
    db_path = os.path.join(tmp_dir, "test.db")
    print(f"\n  Dir temporal: {tmp_dir}")

    try:
        # ── Setup ────────────────────────────────────────────────────────────
        from database import Database
        db     = Database(db_path)
        config = MockConfig()
        ahora  = datetime.now()

        db.inicializar()
        print("\n  Insertando datos de prueba...")
        esperados = generar_sesiones_falsas(db, ahora)
        total_insertado = esperados["total_cobradas"] + esperados["total_canceladas"] + 2
        print(f"  → {esperados['total_cobradas']} cobradas + "
              f"{esperados['total_canceladas']} canceladas + "
              f"2 activas = {total_insertado} sesiones totales")
        print(f"  → Ingresos esperados: S/ {esperados['total_ingresos']:.2f}")

        # ── Tests de BD ──────────────────────────────────────────────────────
        test_01_database_inicializacion(db)
        test_02_registro_entrada(db)
        test_03_cobrar_sesion(db)
        test_04_cancelar_sesion(db)
        test_05_contar_activos(db, esperados_activos=2)
        test_06_get_sesiones_activas(db)
        test_07_get_resumen_rango(db, esperados, ahora)
        test_08_get_ingresos_por_hora(db, ahora)
        test_09_get_ingresos_por_dia(db, ahora)
        test_10_get_ingresos_por_mes_en_anio(db, ahora)
        test_11_get_por_tipo_rango(db, ahora)
        test_12_get_historial_rango(db, ahora)
        test_13_get_totales_globales(db, esperados)

        # ── Tests de Excel ───────────────────────────────────────────────────
        test_14_excel_export(db, config, tmp_dir)
        test_15_coherencia_excel_vs_db(db, config, tmp_dir)
        test_16_edge_cases(db, tmp_dir)
        test_17_integridad_tipos_en_excel(db, config, tmp_dir)

    except Exception as e:
        print(f"\n\033[91m  ERROR FATAL en el runner: {e}\033[0m")
        traceback.print_exc()
        ERRORES.append(f"FATAL: {e}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        print(f"\n  (archivos temporales eliminados)")

    # ── Resumen ──────────────────────────────────────────────────────────────
    print("\n" + "="*60)
    print("  RESUMEN DE RESULTADOS")
    print("="*60)
    if ERRORES:
        print(f"\n  \033[91m✗ {len(ERRORES)} ERROR(ES) ENCONTRADO(S):\033[0m")
        for i, e in enumerate(ERRORES, 1):
            print(f"    {i}. {e}")
    else:
        print(f"\n  \033[92m✓ TODOS LOS TESTS PASARON CORRECTAMENTE\033[0m")

    if AVISOS:
        print(f"\n  \033[93m⚠ {len(AVISOS)} AVISO(S):\033[0m")
        for i, a in enumerate(AVISOS, 1):
            print(f"    {i}. {a}")

    print()
    return len(ERRORES) == 0


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
