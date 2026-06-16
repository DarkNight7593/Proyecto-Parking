"""
ParkingPro - Capa de acceso a datos SQLite
Thread-safe: cada hilo usa su propia conexión (threading.local).

Cambios vs versión anterior:
  - Eliminados métodos obsoletos (get_resumen_hoy, get_ingresos_semana,
    get_ingresos_mes_actual, get_ingresos_ultimos_meses, get_kpi_mes,
    get_por_tipo_hoy) — reemplazados por métodos genéricos de rango.
  - Añadidos: get_resumen_rango, get_ingresos_por_hora,
    get_ingresos_por_dia, get_ingresos_por_mes_en_año,
    get_por_tipo_rango, get_historial_rango, get_historial_rango_count.
  - get_historial_rango ahora acepta offset para paginación.
"""
import sqlite3
import threading
from datetime import datetime
from typing import List, Dict, Optional


class Database:
    """Capa de datos para ParkingPro usando SQLite con conexiones thread-local."""

    def __init__(self, db_path: str = "parkingpro.db"):
        self.db_path = db_path
        # Cada hilo tendrá su propia conexión independiente
        self._local = threading.local()

    def _conn(self) -> sqlite3.Connection:
        """
        Devuelve la conexión SQLite del hilo actual.
        Si no existe, la crea con journal WAL (mayor concurrencia) y
        row_factory para obtener resultados como diccionarios.
        """
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path)
            self._local.conn.row_factory = sqlite3.Row
            # WAL permite lectura concurrente mientras se escribe
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA foreign_keys=ON")
        return self._local.conn
    
    def cerrar_conexion_actual(self):
        """
        Cierra limpiamente la conexión SQLite asociada al hilo actual.
        Evita bloqueos de archivos WAL/SHM en Windows.
        """
        if hasattr(self._local, "conn"):
            try:
                self._local.conn.close()
            except Exception:
                pass
            # Borramos el atributo para que el bolsillo quede vacío
            delattr(self._local, "conn")
    # ─── Inicialización ───────────────────────────────────────────────────────

    def inicializar(self):
        """
        Crea tablas e índices si no existen.
        Es seguro llamarlo varias veces (usa IF NOT EXISTS).
        """
        conn = self._conn()
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

            -- Índices para acelerar las consultas frecuentes
            CREATE INDEX IF NOT EXISTS idx_sesiones_estado  ON sesiones(estado);
            CREATE INDEX IF NOT EXISTS idx_sesiones_placa   ON sesiones(placa);
            CREATE INDEX IF NOT EXISTS idx_sesiones_entrada ON sesiones(hora_entrada);
            CREATE INDEX IF NOT EXISTS idx_sesiones_ticket  ON sesiones(ticket_numero);
        """)
        conn.commit()

    # ─── Generación de número de ticket ──────────────────────────────────────

    def _nuevo_ticket(self) -> str:
        """
        Genera un número de ticket único con formato TKYYYYMMDDxxxx.
        El secuencial se resetea cada día (cuenta tickets del día actual).
        """
        conn = self._conn()
        hoy  = datetime.now().strftime("%Y%m%d")
        row  = conn.execute(
            "SELECT COUNT(*) AS cnt FROM sesiones WHERE ticket_numero LIKE ?",
            (f"TK{hoy}%",),
        ).fetchone()
        seq = (row["cnt"] if row else 0) + 1
        return f"TK{hoy}{seq:04d}"

    # ─── CRUD de sesiones ─────────────────────────────────────────────────────

    def registrar_entrada(self, placa: str, tipo_vehiculo: str,
                          observaciones: str = "") -> Dict:
        """
        Registra la entrada de un vehículo.
        Lanza ValueError si la placa ya tiene una sesión activa.
        Retorna el dict de la sesión creada.
        """
        conn  = self._conn()
        placa = placa.upper().strip()

        # Verificar duplicado de placa activa
        dup = conn.execute(
            "SELECT ticket_numero FROM sesiones WHERE placa=? AND estado='activo'",
            (placa,),
        ).fetchone()
        if dup:
            raise ValueError(
                f"La placa {placa} ya tiene sesión activa (Ticket: {dup['ticket_numero']})"
            )

        ticket = self._nuevo_ticket()
        ahora  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        conn.execute(
            """INSERT INTO sesiones
               (ticket_numero, placa, tipo_vehiculo, hora_entrada, estado, observaciones)
               VALUES (?, ?, ?, ?, 'activo', ?)""",
            (ticket, placa, tipo_vehiculo, ahora, observaciones),
        )
        conn.commit()

        # Devolver la sesión recién creada como diccionario
        return dict(conn.execute(
            "SELECT * FROM sesiones WHERE ticket_numero=?", (ticket,)
        ).fetchone())

    def get_sesiones_activas(self) -> List[Dict]:
        """Retorna todas las sesiones activas ordenadas por hora de entrada descendente."""
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM sesiones WHERE estado='activo' ORDER BY hora_entrada DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_sesion_por_id(self, sesion_id: int) -> Optional[Dict]:
        """Busca una sesión por su ID. Retorna None si no existe."""
        conn = self._conn()
        row  = conn.execute("SELECT * FROM sesiones WHERE id=?", (sesion_id,)).fetchone()
        return dict(row) if row else None

    def get_sesion_activa_por_placa(self, placa: str) -> Optional[Dict]:
        """Busca la sesión activa de una placa. Retorna None si no está activa."""
        conn = self._conn()
        row  = conn.execute(
            "SELECT * FROM sesiones WHERE placa=? AND estado='activo'",
            (placa.upper().strip(),),
        ).fetchone()
        return dict(row) if row else None
    
    def cobrar_sesion(self, sesion_id: int, monto: float, minutos_fijos: Optional[int] = None, hora_salida_fija: Optional[str] = None) -> Dict:
        """
        Cierra la sesión. Recibe parámetros fijos desde la UI para garantizar 
        que el ticket, la BD y la pantalla estén matemáticamente sincronizados.
        """
        conn   = self._conn()
        sesion = self.get_sesion_por_id(sesion_id)

        if not sesion:
            raise ValueError(f"Sesión {sesion_id} no encontrada")
        if sesion["estado"] != "activo":
            raise ValueError(f"La sesión {sesion_id} no está activa")

        # 1. Si el modal nos manda una hora exacta, la usamos. Si no, calculamos.
        if hora_salida_fija is not None:
            ahora = hora_salida_fija
        else:
            ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
        # 2. Si el modal nos manda minutos exactos, los usamos.
        if minutos_fijos is not None:
            minutos = minutos_fijos
        else:
            entrada = datetime.strptime(sesion["hora_entrada"], "%Y-%m-%d %H:%M:%S")
            salida  = datetime.strptime(ahora, "%Y-%m-%d %H:%M:%S")
            minutos = max(1, int((salida - entrada).total_seconds() / 60))

        # 3. Guardamos en BD los datos matemáticamente perfectos
        conn.execute(
            """UPDATE sesiones
               SET hora_salida=?, minutos_total=?, monto=?, estado='cobrado'
               WHERE id=?""",
            (ahora, minutos, round(monto, 2), sesion_id),
        )
        conn.commit()
        return self.get_sesion_por_id(sesion_id)

    def cancelar_sesion(self, sesion_id: int):
            conn = self._conn()
            
            # Guardamos el resultado del execute en una variable 'cursor'
            cursor = conn.execute(
                "UPDATE sesiones SET estado='cancelado' WHERE id=? AND estado='activo'",
                (sesion_id,)
            )
            conn.commit()
            
            # Verificamos si realmente se actualizó alguna fila
            if cursor.rowcount == 0:
                # Si no se actualizó nada, investigamos por qué falló
                sesion = self.get_sesion_por_id(sesion_id)
                if not sesion:
                    raise ValueError(f"Sesión {sesion_id} no encontrada en la base de datos.")
                
                # Si la sesión existe, es porque su estado ya no era 'activo'
                raise ValueError(
                    f"La sesión ya está '{sesion['estado']}' y no se puede cancelar."
                )

    def contar_activos(self) -> int:
        """Cuenta los vehículos actualmente en el estacionamiento."""
        conn = self._conn()
        row  = conn.execute(
            "SELECT COUNT(*) AS n FROM sesiones WHERE estado='activo'"
        ).fetchone()
        return row["n"] if row else 0

    # ─── KPIs y Reportes (por rango de fechas) ────────────────────────────────
    # Todos los métodos de reporte usan fechas en formato 'YYYY-MM-DD'.
    # Esto permite reutilizarlos para Hoy, Semana, Mes y Año.

    def get_resumen_rango(self, fecha_inicio: str, fecha_fin: str) -> Dict:
        """
        KPIs agregados para un rango de fechas.

        Retorna:
          total_vehiculos  — todos los registros del período (cualquier estado)
          cobrados         — sesiones que terminaron con pago exitoso
          cancelados       — sesiones anuladas sin cobro (ej. entrada por error)
          activos_ahora    — vehículos aún dentro del estacionamiento
          ingresos         — suma del monto cobrado (solo estado='cobrado')
          prom_minutos     — tiempo promedio de estadía (solo sesiones cobradas)

        Ejemplo: get_resumen_rango("2025-01-01", "2025-01-31")
        """
        conn = self._conn()
        row = conn.execute("""
            SELECT
                COUNT(*)                                                      AS total_vehiculos,
                COUNT(CASE WHEN estado='cobrado'   THEN 1 END)                AS cobrados,
                COUNT(CASE WHEN estado='cancelado' THEN 1 END)                AS cancelados,
                COUNT(CASE WHEN estado='activo'    THEN 1 END)                AS activos_ahora,
                COALESCE(SUM(CASE WHEN estado='cobrado' THEN monto END), 0)   AS ingresos,
                COALESCE(AVG(CASE WHEN estado='cobrado'
                                  THEN minutos_total END), 0)                 AS prom_minutos
            FROM sesiones
            WHERE DATE(hora_entrada) BETWEEN ? AND ?
        """, (fecha_inicio, fecha_fin)).fetchone()
        return dict(row) if row else {}

    def get_ingresos_por_hora(self, fecha: str) -> List[Dict]:
        """
        Ingresos agrupados por hora del día para un día específico.
        Usado en la vista 'Hoy' del panel de reportes.
        Retorna: [{hora: 'HH', vehiculos: N, ingresos: X.XX}, ...]
        """
        conn = self._conn()
        rows = conn.execute("""
            SELECT
                strftime('%H', hora_entrada) AS hora,
                COUNT(*)                     AS vehiculos,
                COALESCE(SUM(monto), 0)      AS ingresos
            FROM sesiones
            WHERE estado='cobrado' AND DATE(hora_entrada) = ?
            GROUP BY strftime('%H', hora_entrada)
            ORDER BY hora ASC
        """, (fecha,)).fetchall()
        return [dict(r) for r in rows]

    def get_ingresos_por_dia(self, fecha_inicio: str, fecha_fin: str) -> List[Dict]:
        """
        Ingresos agrupados por día para un rango de fechas.
        Usado en vistas 'Semana' y 'Mes'.
        Retorna: [{fecha: 'YYYY-MM-DD', vehiculos: N, ingresos: X.XX}, ...]
        """
        conn = self._conn()
        rows = conn.execute("""
            SELECT
                DATE(hora_entrada)      AS fecha,
                COUNT(*)               AS vehiculos,
                COALESCE(SUM(monto), 0) AS ingresos
            FROM sesiones
            WHERE estado='cobrado' AND DATE(hora_entrada) BETWEEN ? AND ?
            GROUP BY DATE(hora_entrada)
            ORDER BY fecha ASC
        """, (fecha_inicio, fecha_fin)).fetchall()
        return [dict(r) for r in rows]

    def get_ingresos_por_mes_en_año(self, año: int) -> List[Dict]:
        """
        Ingresos agrupados por mes para un año completo.
        Usado en la vista 'Año'.
        Retorna: [{mes: 'MM', vehiculos: N, ingresos: X.XX}, ...]
        """
        conn = self._conn()
        rows = conn.execute("""
            SELECT
                strftime('%m', hora_entrada) AS mes,
                COUNT(*)                     AS vehiculos,
                COALESCE(SUM(monto), 0)      AS ingresos
            FROM sesiones
            WHERE estado='cobrado' AND strftime('%Y', hora_entrada) = ?
            GROUP BY strftime('%m', hora_entrada)
            ORDER BY mes ASC
        """, (str(año),)).fetchall()
        return [dict(r) for r in rows]

    def get_por_tipo_rango(self, fecha_inicio: str, fecha_fin: str) -> List[Dict]:
        """
        Cantidad de vehículos e ingresos por tipo para un rango de fechas.
        Solo sesiones cobradas (excluye activas y canceladas).
        Retorna: [{tipo_vehiculo, cantidad, ingresos}, ...] ordenado por cantidad DESC.
        """
        conn = self._conn()
        rows = conn.execute("""
            SELECT
                tipo_vehiculo,
                COUNT(*)               AS cantidad,
                COALESCE(SUM(monto), 0) AS ingresos
            FROM sesiones
            WHERE estado='cobrado' AND DATE(hora_entrada) BETWEEN ? AND ?
            GROUP BY tipo_vehiculo
            ORDER BY cantidad DESC
        """, (fecha_inicio, fecha_fin)).fetchall()
        return [dict(r) for r in rows]

    def get_historial_rango_count(self, fecha_inicio: str, fecha_fin: str) -> int:
        """
        Cuenta el total de sesiones finalizadas (cobradas y canceladas) en un rango.
        Usado para calcular el número total de páginas en la vista paginada.
        """
        conn = self._conn()
        row = conn.execute("""
            SELECT COUNT(*) AS total FROM sesiones
            WHERE estado != 'activo'
              AND DATE(hora_entrada) BETWEEN ? AND ?
        """, (fecha_inicio, fecha_fin)).fetchone()
        return row["total"] if row else 0

    def get_historial_rango(self, fecha_inicio: str, fecha_fin: str,
                            limit: int = 30, offset: int = 0) -> List[Dict]:
        """
        Historial de sesiones finalizadas (cobradas y canceladas) en un rango.
        No incluye sesiones activas. Ordenadas por hora de entrada descendente.
        Soporta paginación mediante limit y offset.
        """
        conn = self._conn()
        rows = conn.execute("""
            SELECT * FROM sesiones
            WHERE estado != 'activo'
              AND DATE(hora_entrada) BETWEEN ? AND ?
            ORDER BY hora_entrada DESC
            LIMIT ? OFFSET ?
        """, (fecha_inicio, fecha_fin, limit, offset)).fetchall()
        return [dict(r) for r in rows]

    def get_historial(self, limit: int = 100, offset: int = 0,
                      fecha: str = None, placa: str = None) -> List[Dict]:
        """
        Historial genérico con filtros opcionales por fecha y placa.
        Útil para búsquedas avanzadas (no usado en el panel de reportes
        estándar, pero disponible para extensiones futuras).
        """
        conn   = self._conn()
        params: list = []
        conds  = ["estado != 'activo'"]

        if fecha:
            conds.append("DATE(hora_entrada) = ?")
            params.append(fecha)
        if placa:
            conds.append("placa LIKE ?")
            params.append(f"%{placa.upper()}%")

        where  = " AND ".join(conds)
        params += [limit, offset]
        rows   = conn.execute(
            f"SELECT * FROM sesiones WHERE {where} ORDER BY hora_entrada DESC LIMIT ? OFFSET ?",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def get_totales_globales(self) -> Dict:
        """
        Totales acumulados de toda la historia del negocio.
        Incluye desglose entre sesiones cobradas y canceladas.
        Útil para pantallas de resumen general y exportación Excel.
        """
        conn = self._conn()
        row  = conn.execute("""
            SELECT
                COUNT(CASE WHEN estado='cobrado'   THEN 1 END) AS total_sesiones,
                COUNT(CASE WHEN estado='cancelado' THEN 1 END) AS canceladas,
                COUNT(*)                                        AS total_ingresaron,
                COALESCE(SUM(CASE WHEN estado='cobrado' THEN monto END), 0) AS ingresos_totales,
                COALESCE(MAX(CASE WHEN estado='cobrado' THEN monto END), 0) AS ticket_maximo
            FROM sesiones
        """).fetchone()
        return dict(row) if row else {}