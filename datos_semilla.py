"""
ParkingPro — Script de Datos de Prueba
========================================
Puebla la base de datos con sesiones realistas para validar reportes y Excel.

USO:
    python seed_datos.py               # usa config.ini automáticamente
    python seed_datos.py mi_db.db      # ruta manual a la BD

LO QUE GENERA (configurable abajo):
    • Hoy             : ~25 sesiones  (mix activas + cobradas del día)
    • Este mes        : ~20 días con  10–35 sesiones/día
    • Últimos 5 meses : ~20 días/mes  con variación realista por mes
    • Canceladas      : ~4% del total
    • Activas al cierre: entre 3 y 8 vehículos

IMPORTANTE: El script detecta si ya hay datos y pregunta antes de continuar.
"""

import os
import sys
import math
import sqlite3
import random
import configparser
from datetime import datetime, timedelta
from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# PARÁMETROS AJUSTABLES
# ─────────────────────────────────────────────────────────────────────────────

MESES_ATRAS        = 5      # cuántos meses anteriores al actual generar
SESIONES_HOY_MIN   = 20     # mínimo de sesiones para hoy
SESIONES_HOY_MAX   = 30     # máximo de sesiones para hoy
SESIONES_DIA_MIN   = 8      # mínimo por día en meses anteriores
SESIONES_DIA_MAX   = 35     # máximo por día en meses anteriores
DIAS_ACTIVOS_MES   = 24     # días con actividad por mes (excluye algunos domingos)
PCT_CANCELADAS     = 0.04   # porcentaje de sesiones que se cancelan (0.04 = 4%)
ACTIVAS_AL_CIERRE  = 5      # vehículos que quedan activos al correr el script

# Distribución de tipos de vehículo (debe sumar 1.0)
DISTRIBUCION_TIPOS = {
    "Auto":       0.45,
    "Moto":       0.20,
    "Camioneta":  0.18,
    "Bus":        0.05,
    "Camión":     0.05,
    "Bicicleta":  0.07,
}

# Franja horaria de operación del estacionamiento
HORA_APERTURA = 6   # 06:00
HORA_CIERRE   = 22  # 22:00

# Placas de ejemplo por tipo (10 por tipo para variedad)
PLACAS = {
    "Auto":      ["ABC-123","DEF-456","GHI-789","JKL-012","MNO-345",
                  "PQR-678","STU-901","VWX-234","YZA-567","BCD-890"],
    "Moto":      ["M0T-001","M0T-002","M0T-003","M0T-004","M0T-005",
                  "M0T-006","M0T-007","M0T-008","M0T-009","M0T-010"],
    "Camioneta": ["CAM-111","CAM-222","CAM-333","CAM-444","CAM-555",
                  "CAM-666","CAM-777","CAM-888","CAM-999","CAM-000"],
    "Bus":       ["BUS-001","BUS-002","BUS-003","BUS-004","BUS-005",
                  "BUS-006","BUS-007","BUS-008","BUS-009","BUS-010"],
    "Camión":    ["CMN-001","CMN-002","CMN-003","CMN-004","CMN-005",
                  "CMN-006","CMN-007","CMN-008","CMN-009","CMN-010"],
    "Bicicleta": ["BIC-001","BIC-002","BIC-003","BIC-004","BIC-005",
                  "BIC-006","BIC-007","BIC-008","BIC-009","BIC-010"],
}

# ─────────────────────────────────────────────────────────────────────────────
# TARIFAS POR DEFECTO (se sobreescriben si se lee config.ini)
# ─────────────────────────────────────────────────────────────────────────────

TARIFAS_DEFAULT = {
    "Auto":       2.0,
    "Moto":       1.5,
    "Camioneta":  3.0,
    "Bus":        5.0,
    "Camión":     5.0,
    "Bicicleta":  1.0,
}

TIEMPO_LIBRE_DEFAULT = 0   # minutos de gracia
MONEDA_DEFAULT       = "S/"

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def calcular_monto(minutos: int, tarifa: float, tiempo_libre: int = 0) -> float:
    """Réplica exacta de modal_cobro.calcular_monto."""
    if minutos <= tiempo_libre:
        return 0.0
    horas = math.ceil((minutos - tiempo_libre) / 60)
    return round(horas * tarifa, 2)


def peso_hora(hora: int) -> float:
    """
    Probabilidad relativa de que un vehículo ENTRE a cierta hora.
    Pico mañana (9-11h) y pico tarde (17-19h).
    """
    curva = {6:0.3, 7:0.5, 8:0.8, 9:1.0, 10:0.9, 11:0.8,
             12:0.7, 13:0.6, 14:0.5, 15:0.5, 16:0.7,
             17:1.0, 18:0.9, 19:0.7, 20:0.4, 21:0.2}
    return curva.get(hora, 0.1)


def hora_aleatoria(fecha_dt: datetime) -> datetime:
    """Genera un datetime con hora aleatoria ponderada para un día dado."""
    horas_pool = list(range(HORA_APERTURA, HORA_CIERRE))
    pesos = [peso_hora(h) for h in horas_pool]
    hora = random.choices(horas_pool, weights=pesos, k=1)[0]
    minuto = random.randint(0, 59)
    segundo = random.randint(0, 59)
    return fecha_dt.replace(hour=hora, minute=minuto, second=segundo, microsecond=0)


def duracion_aleatoria(tipo: str) -> int:
    """
    Duración en minutos según distribución realista por tipo.
    Motos y bicis tienden a estadías cortas; camiones, más largas.
    """
    rangos = {
        "Auto":      (10, 240),
        "Moto":      (5,  120),
        "Camioneta": (15, 300),
        "Bus":       (20, 480),
        "Camión":    (30, 480),
        "Bicicleta": (5,  90),
    }
    lo, hi = rangos.get(tipo, (10, 180))
    # Exponencial truncada: muchas estadías cortas, pocas largas
    raw = random.expovariate(1 / ((lo + hi) / 3))
    return max(lo, min(hi, int(raw)))


def tipo_aleatorio() -> str:
    tipos  = list(DISTRIBUCION_TIPOS.keys())
    pesos  = list(DISTRIBUCION_TIPOS.values())
    return random.choices(tipos, weights=pesos, k=1)[0]


def placa_aleatoria(tipo: str, usadas: set) -> str:
    """Selecciona una placa del pool del tipo que no esté actualmente en uso."""
    pool = PLACAS[tipo][:]
    random.shuffle(pool)
    for p in pool:
        if p not in usadas:
            return p
    # Si todas están en uso, genera una placa random
    letras = "ABCDEFGHJKLMNPQRSTUVWXYZ"
    while True:
        p = f"{random.choice(letras)}{random.choice(letras)}{random.choice(letras)}-{random.randint(100,999)}"
        if p not in usadas:
            return p


def nuevo_ticket(conn: sqlite3.Connection, fecha_dt: datetime) -> str:
    """
    Genera ticket único para la fecha dada. Replica la lógica de database.py
    pero seguro ante concurrencia (solo hilo principal en este script).
    """
    hoy = fecha_dt.strftime("%Y%m%d")
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM sesiones WHERE ticket_numero LIKE ?",
        (f"TK{hoy}%",),
    ).fetchone()
    seq = row[0] + 1
    return f"TK{hoy}{seq:04d}"


def leer_config(script_dir: str) -> tuple:
    """Lee config.ini y retorna (tarifas_dict, tiempo_libre, moneda)."""
    config_path = os.path.join(script_dir, "config.ini")
    if not os.path.exists(config_path):
        print(f"  [config] config.ini no encontrado en {script_dir} → usando valores por defecto")
        return TARIFAS_DEFAULT.copy(), TIEMPO_LIBRE_DEFAULT, MONEDA_DEFAULT

    cfg = configparser.ConfigParser()
    cfg.read(config_path, encoding="utf-8")

    clave_a_nombre = {
        "auto": "Auto", "moto": "Moto", "camioneta": "Camioneta",
        "bus": "Bus", "camion": "Camión", "bicicleta": "Bicicleta",
    }

    tarifas = {}
    for clave, nombre in clave_a_nombre.items():
        try:
            tarifas[nombre] = float(cfg.get("tarifas", clave, fallback="2.0"))
        except (ValueError, configparser.Error):
            tarifas[nombre] = TARIFAS_DEFAULT[nombre]

    try:
        tl = int(cfg.get("sistema", "tiempo_libre_min", fallback="0"))
    except (ValueError, configparser.Error):
        tl = TIEMPO_LIBRE_DEFAULT

    moneda = cfg.get("sistema", "moneda", fallback=MONEDA_DEFAULT)
    print(f"  [config] Leído config.ini: tiempo_libre={tl} min, moneda={moneda}")
    print(f"  [config] Tarifas: { {k: v for k, v in tarifas.items()} }")
    return tarifas, tl, moneda


def resolver_db_path(script_dir: str) -> str:
    """Resuelve la ruta a la BD desde config.ini o usa el default."""
    config_path = os.path.join(script_dir, "config.ini")
    if os.path.exists(config_path):
        cfg = configparser.ConfigParser()
        cfg.read(config_path, encoding="utf-8")
        db_path = cfg.get("sistema", "db_path", fallback="parkingpro.db")
        if not os.path.isabs(db_path):
            db_path = os.path.join(script_dir, db_path)
        return db_path
    return os.path.join(script_dir, "parkingpro.db")


# ─────────────────────────────────────────────────────────────────────────────
# GENERADOR PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

def generar_sesiones_dia(
    conn: sqlite3.Connection,
    fecha: datetime,
    n_sesiones: int,
    tarifas: dict,
    tiempo_libre: int,
    permitir_activas: bool = False,
    n_activas_deseadas: int = 0,
) -> dict:
    """
    Inserta `n_sesiones` para el día `fecha`.
    Retorna contadores: cobradas, canceladas, activas, ingresos.
    """
    placas_activas_hoy: set = set()
    contadores = {"cobradas": 0, "canceladas": 0, "activas": 0, "ingresos": 0.0}

    activas_insertadas = 0

    for _ in range(n_sesiones):
        tipo  = tipo_aleatorio()
        placa = placa_aleatoria(tipo, placas_activas_hoy)
        tarifa = tarifas.get(tipo, 2.0)

        hora_entrada = hora_aleatoria(fecha)
        ticket = nuevo_ticket(conn, hora_entrada)

        # ── Decidir estado ────────────────────────────────────────────────────
        es_cancelada = random.random() < PCT_CANCELADAS
        es_activa    = (
            permitir_activas
            and not es_cancelada
            and activas_insertadas < n_activas_deseadas
            and hora_entrada.hour >= HORA_APERTURA
        )

        if es_cancelada:
            # Sesiones canceladas: solo tienen hora_entrada
            conn.execute(
                """INSERT INTO sesiones
                   (ticket_numero, placa, tipo_vehiculo, hora_entrada, estado, created_at)
                   VALUES (?, ?, ?, ?, 'cancelado', ?)""",
                (ticket, placa, tipo, hora_entrada.strftime("%Y-%m-%d %H:%M:%S"),
                 hora_entrada.strftime("%Y-%m-%d %H:%M:%S")),
            )
            contadores["canceladas"] += 1

        elif es_activa:
            # Sesiones activas: solo tienen hora_entrada (el vehículo sigue dentro)
            conn.execute(
                """INSERT INTO sesiones
                   (ticket_numero, placa, tipo_vehiculo, hora_entrada, estado, created_at)
                   VALUES (?, ?, ?, ?, 'activo', ?)""",
                (ticket, placa, tipo, hora_entrada.strftime("%Y-%m-%d %H:%M:%S"),
                 hora_entrada.strftime("%Y-%m-%d %H:%M:%S")),
            )
            placas_activas_hoy.add(placa)
            activas_insertadas += 1
            contadores["activas"] += 1

        else:
            # Sesiones cobradas: tienen hora_salida, minutos y monto calculados
            duracion = duracion_aleatoria(tipo)
            hora_salida = hora_entrada + timedelta(minutes=duracion)

            # No pasar de las 23:59 del mismo día
            limite_dia = fecha.replace(hour=23, minute=59, second=0, microsecond=0)
            if hora_salida > limite_dia:
                hora_salida = limite_dia
                duracion = max(1, int((hora_salida - hora_entrada).total_seconds() / 60))

            # Truncar a minutos exactos (igual que el modal)
            entrada_limpia = hora_entrada.replace(second=0, microsecond=0)
            salida_limpia  = hora_salida.replace(second=0, microsecond=0)
            minutos = max(1, int((salida_limpia - entrada_limpia).total_seconds() / 60))
            monto   = calcular_monto(minutos, tarifa, tiempo_libre)

            conn.execute(
                """INSERT INTO sesiones
                   (ticket_numero, placa, tipo_vehiculo,
                    hora_entrada, hora_salida, minutos_total, monto, estado, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'cobrado', ?)""",
                (ticket, placa, tipo,
                 hora_entrada.strftime("%Y-%m-%d %H:%M:%S"),
                 salida_limpia.strftime("%Y-%m-%d %H:%M:%S"),
                 minutos, monto,
                 hora_entrada.strftime("%Y-%m-%d %H:%M:%S")),
            )
            placas_activas_hoy.add(placa)
            contadores["cobradas"] += 1
            contadores["ingresos"] += monto

    conn.commit()
    return contadores


def main():
    random.seed(42)  # reproducible; quita esta línea para datos distintos cada ejecución

    # ── Resolver rutas ─────────────────────────────────────────────────────────
    script_dir = (
        os.path.dirname(os.path.abspath(sys.argv[0]))
        if sys.argv[0]
        else os.getcwd()
    )

    if len(sys.argv) > 1:
        db_path = sys.argv[1]
        print(f"\n[+] BD desde argumento: {db_path}")
    else:
        db_path = resolver_db_path(script_dir)
        print(f"\n[+] BD detectada: {db_path}")

    tarifas, tiempo_libre, moneda = leer_config(script_dir)

    # ── Verificar si la BD ya tiene datos ─────────────────────────────────────
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    # Crear tabla si no existe (por si se corre en BD virgen)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sesiones (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_numero TEXT    UNIQUE NOT NULL,
            placa         TEXT    NOT NULL,
            tipo_vehiculo TEXT    NOT NULL,
            hora_entrada  TEXT    NOT NULL,
            hora_salida   TEXT,
            minutos_total INTEGER,
            monto         REAL,
            estado        TEXT    NOT NULL DEFAULT 'activo',
            observaciones TEXT,
            created_at    TEXT    DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_sesiones_estado  ON sesiones(estado);
        CREATE INDEX IF NOT EXISTS idx_sesiones_placa   ON sesiones(placa);
        CREATE INDEX IF NOT EXISTS idx_sesiones_entrada ON sesiones(hora_entrada);
        CREATE INDEX IF NOT EXISTS idx_sesiones_ticket  ON sesiones(ticket_numero);
    """)
    conn.commit()

    total_existente = conn.execute("SELECT COUNT(*) FROM sesiones").fetchone()[0]
    if total_existente > 0:
        print(f"\n⚠  La BD ya tiene {total_existente} registros.")
        respuesta = input("   ¿Agregar datos de prueba encima? [s/N]: ").strip().lower()
        if respuesta not in ("s", "si", "sí", "y", "yes"):
            print("   Abortado. No se modificó nada.")
            conn.close()
            return

    # ── Calcular rango de fechas ───────────────────────────────────────────────
    hoy = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    print(f"\n{'─'*60}")
    print(f" Generando datos de prueba para ParkingPro")
    print(f" Rango: {(hoy - timedelta(days=MESES_ATRAS*30)).strftime('%d/%m/%Y')} → hoy ({hoy.strftime('%d/%m/%Y')})")
    print(f"{'─'*60}\n")

    total_cobradas = 0
    total_canceladas = 0
    total_activas = 0
    total_ingresos = 0.0

    # ── HOY ───────────────────────────────────────────────────────────────────
    print(f"  📅 Hoy ({hoy.strftime('%d/%m/%Y')})...", end=" ")
    n = random.randint(SESIONES_HOY_MIN, SESIONES_HOY_MAX)
    c = generar_sesiones_dia(
        conn, hoy, n, tarifas, tiempo_libre,
        permitir_activas=True,
        n_activas_deseadas=ACTIVAS_AL_CIERRE,
    )
    total_cobradas   += c["cobradas"]
    total_canceladas += c["canceladas"]
    total_activas    += c["activas"]
    total_ingresos   += c["ingresos"]
    print(f"✓ {c['cobradas']} cobradas, {c['canceladas']} canceladas, {c['activas']} activas | {moneda} {c['ingresos']:.2f}")

    # ── DÍAS DE ESTE MES (antes de hoy) ───────────────────────────────────────
    primer_dia_mes = hoy.replace(day=1)
    dias_este_mes  = [(primer_dia_mes + timedelta(days=i))
                      for i in range((hoy - primer_dia_mes).days)
                      if (primer_dia_mes + timedelta(days=i)).weekday() != 6 or random.random() > 0.4]

    if dias_este_mes:
        print(f"\n  📅 Este mes ({hoy.strftime('%B %Y')}) — {len(dias_este_mes)} días:")
        for dia in dias_este_mes:
            n = random.randint(SESIONES_DIA_MIN, SESIONES_DIA_MAX)
            c = generar_sesiones_dia(conn, dia, n, tarifas, tiempo_libre)
            total_cobradas   += c["cobradas"]
            total_canceladas += c["canceladas"]
            total_ingresos   += c["ingresos"]
            print(f"    {dia.strftime('%d/%m')} → {c['cobradas']+c['canceladas']:3d} sesiones | {moneda} {c['ingresos']:>8.2f}")

    # ── MESES ANTERIORES ─────────────────────────────────────────────────────
    for m in range(1, MESES_ATRAS + 1):
        # Primer día del mes correspondiente
        año_ref = hoy.year
        mes_ref = hoy.month - m
        if mes_ref <= 0:
            mes_ref += 12
            año_ref -= 1

        primer_dia = datetime(año_ref, mes_ref, 1)
        # Último día del mes
        if mes_ref == 12:
            ultimo_dia = datetime(año_ref + 1, 1, 1) - timedelta(days=1)
        else:
            ultimo_dia = datetime(año_ref, mes_ref + 1, 1) - timedelta(days=1)

        # Seleccionar DIAS_ACTIVOS_MES días del mes con algo de aleatoriedad
        todos_los_dias = [primer_dia + timedelta(days=i)
                          for i in range((ultimo_dia - primer_dia).days + 1)]
        # Excluir algunos domingos aleatoriamente (negocio no siempre abre domingos)
        candidatos = [d for d in todos_los_dias
                      if d.weekday() != 6 or random.random() > 0.35]
        dias_mes = sorted(random.sample(candidatos, min(DIAS_ACTIVOS_MES, len(candidatos))))

        ingreso_mes = 0.0
        sesiones_mes = 0
        print(f"\n  📅 {primer_dia.strftime('%B %Y')} — {len(dias_mes)} días:")

        # Factor estacional: meses de verano/vacaciones tienen más actividad
        factor_mes = 1.0
        if mes_ref in (1, 2, 7, 8):    # enero, feb, jul, ago → temporada alta
            factor_mes = 1.25
        elif mes_ref in (4, 10, 11):    # apr, oct, nov → temporada media-alta
            factor_mes = 1.10

        for dia in dias_mes:
            n = int(random.randint(SESIONES_DIA_MIN, SESIONES_DIA_MAX) * factor_mes)
            c = generar_sesiones_dia(conn, dia, n, tarifas, tiempo_libre)
            ingreso_mes  += c["ingresos"]
            sesiones_mes += c["cobradas"] + c["canceladas"]
            total_cobradas   += c["cobradas"]
            total_canceladas += c["canceladas"]
            total_ingresos   += c["ingresos"]
            print(f"    {dia.strftime('%d/%m')} → {c['cobradas']+c['canceladas']:3d} sesiones | {moneda} {c['ingresos']:>8.2f}")

        print(f"    {'─'*40}")
        print(f"    Subtotal {primer_dia.strftime('%B')}: {sesiones_mes} sesiones | {moneda} {ingreso_mes:.2f}")

    # ── RESUMEN FINAL ─────────────────────────────────────────────────────────
    total_registros = conn.execute("SELECT COUNT(*) FROM sesiones").fetchone()[0]
    print(f"\n{'═'*60}")
    print(f"  ✅ DATOS GENERADOS CORRECTAMENTE")
    print(f"{'─'*60}")
    print(f"  Sesiones cobradas  : {total_cobradas:>6}")
    print(f"  Sesiones canceladas: {total_canceladas:>6}  ({PCT_CANCELADAS*100:.0f}% aprox.)")
    print(f"  Sesiones activas   : {total_activas:>6}  (vehículos dentro ahora)")
    print(f"  Total en BD        : {total_registros:>6}")
    print(f"  Ingresos totales   : {moneda} {total_ingresos:>10.2f}")
    print(f"{'═'*60}")
    print(f"\n  Abre ParkingPro y ve al panel de Reportes para verificar.")
    print(f"  La BD está en: {db_path}\n")

    conn.close()


if __name__ == "__main__":
    main()