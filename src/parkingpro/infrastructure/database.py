"""Persistencia SQLite de ParkingPro."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from parkingpro.domain.errors import (
    DuplicateActiveSessionError,
    InvalidSessionStateError,
    SessionNotFoundError,
    ValidationError,
)
from parkingpro.domain.parking import (
    DATETIME_FORMAT,
    MAX_PLATE_LENGTH,
    SessionStatus,
    elapsed_minutes,
    validate_amount,
    validate_plate,
    validate_vehicle_type,
)


class Database:
    """Repositorio SQLite con una conexión independiente por hilo."""

    PLACA_MAX_CHARS = MAX_PLATE_LENGTH

    def __init__(
        self,
        db_path: str | Path = "parkingpro.db",
        *,
        clock: Callable[[], datetime] = datetime.now,
        timeout_seconds: float = 10.0,
    ):
        self.db_path = str(db_path)
        self._clock = clock
        self._timeout_seconds = timeout_seconds
        self._local = threading.local()

    def _conn(self) -> sqlite3.Connection:
        connection = getattr(self._local, "connection", None)
        if connection is None:
            connection = sqlite3.connect(
                self.db_path,
                timeout=self._timeout_seconds,
                isolation_level=None,
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(f"PRAGMA busy_timeout = {int(self._timeout_seconds * 1000)}")
            if self.db_path != ":memory:":
                connection.execute("PRAGMA journal_mode = WAL")
                connection.execute("PRAGMA synchronous = NORMAL")
            self._local.connection = connection
        return connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._conn()
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield connection
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()

    def cerrar_conexion_actual(self) -> None:
        connection = getattr(self._local, "connection", None)
        if connection is None:
            return
        try:
            connection.close()
        finally:
            del self._local.connection

    close = cerrar_conexion_actual

    def __enter__(self) -> Database:
        self.inicializar()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def inicializar(self) -> None:
        connection = self._conn()
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS sesiones (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_numero TEXT    UNIQUE NOT NULL,
                placa         TEXT    NOT NULL,
                tipo_vehiculo TEXT    NOT NULL,
                hora_entrada  TEXT    NOT NULL,
                hora_salida   TEXT,
                minutos_total INTEGER CHECK (minutos_total IS NULL OR minutos_total >= 1),
                monto         REAL    CHECK (monto IS NULL OR monto >= 0),
                estado        TEXT    NOT NULL DEFAULT 'activo'
                                      CHECK (estado IN ('activo', 'cobrado', 'cancelado')),
                observaciones TEXT    NOT NULL DEFAULT '',
                created_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
            );

            CREATE INDEX IF NOT EXISTS idx_sesiones_estado
                ON sesiones(estado);
            CREATE INDEX IF NOT EXISTS idx_sesiones_placa
                ON sesiones(placa);
            CREATE INDEX IF NOT EXISTS idx_sesiones_entrada
                ON sesiones(hora_entrada);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_sesiones_placa_activa
                ON sesiones(placa) WHERE estado = 'activo';
            CREATE UNIQUE INDEX IF NOT EXISTS idx_sesiones_placa_activa_normalizada
                ON sesiones(UPPER(TRIM(placa))) WHERE estado = 'activo';
            """
        )

    def _nuevo_ticket(self, connection: sqlite3.Connection, now: datetime) -> str:
        prefix = f"TK{now:%Y%m%d}"
        row = connection.execute(
            """
            SELECT COALESCE(MAX(CAST(SUBSTR(ticket_numero, 11) AS INTEGER)), 0) AS seq
            FROM sesiones
            WHERE ticket_numero GLOB ?
            """,
            (f"{prefix}[0-9][0-9][0-9][0-9]",),
        ).fetchone()
        sequence = int(row["seq"]) + 1
        if sequence > 9999:
            raise ValidationError("Se alcanzó el límite diario de tickets")
        return f"{prefix}{sequence:04d}"

    @staticmethod
    def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    def registrar_entrada(
        self,
        placa: str,
        tipo_vehiculo: str,
        observaciones: str = "",
    ) -> dict[str, Any]:
        plate = validate_plate(placa)
        vehicle_type = validate_vehicle_type(tipo_vehiculo)
        notes = observaciones.strip() if isinstance(observaciones, str) else ""
        now = self._clock()

        try:
            with self._transaction() as connection:
                duplicate = connection.execute(
                    """
                    SELECT ticket_numero FROM sesiones
                    WHERE UPPER(TRIM(placa)) = ? AND estado = 'activo'
                    """,
                    (plate,),
                ).fetchone()
                if duplicate:
                    raise DuplicateActiveSessionError(
                        f"La placa {plate} ya tiene sesión activa "
                        f"(Ticket: {duplicate['ticket_numero']})"
                    )

                ticket = self._nuevo_ticket(connection, now)
                cursor = connection.execute(
                    """
                    INSERT INTO sesiones (
                        ticket_numero, placa, tipo_vehiculo,
                        hora_entrada, estado, observaciones
                    ) VALUES (?, ?, ?, ?, 'activo', ?)
                    """,
                    (ticket, plate, vehicle_type, now.strftime(DATETIME_FORMAT), notes),
                )
                row = connection.execute(
                    "SELECT * FROM sesiones WHERE id = ?",
                    (cursor.lastrowid,),
                ).fetchone()
        except sqlite3.IntegrityError as exc:
            if "placa" in str(exc).lower():
                raise DuplicateActiveSessionError(
                    f"La placa {plate} ya tiene una sesión activa"
                ) from exc
            raise

        result = self._row_to_dict(row)
        if result is None:
            raise RuntimeError("No se pudo recuperar la sesión creada")
        return result

    def get_sesiones_activas(self) -> list[dict[str, Any]]:
        rows = (
            self._conn()
            .execute(
                """
            SELECT * FROM sesiones
            WHERE estado = 'activo'
            ORDER BY hora_entrada DESC, id DESC
            """
            )
            .fetchall()
        )
        return [dict(row) for row in rows]

    def get_sesion_por_id(self, sesion_id: int) -> dict[str, Any] | None:
        row = (
            self._conn()
            .execute(
                "SELECT * FROM sesiones WHERE id = ?",
                (sesion_id,),
            )
            .fetchone()
        )
        return self._row_to_dict(row)

    def get_sesion_activa_por_placa(self, placa: str) -> dict[str, Any] | None:
        try:
            plate = validate_plate(placa)
        except ValidationError:
            return None
        row = (
            self._conn()
            .execute(
                """
            SELECT * FROM sesiones
            WHERE UPPER(TRIM(placa)) = ? AND estado = 'activo'
            """,
                (plate,),
            )
            .fetchone()
        )
        return self._row_to_dict(row)

    def cobrar_sesion(
        self,
        sesion_id: int,
        monto: float,
        minutos_fijos: int | None = None,
        hora_salida_fija: str | None = None,
    ) -> dict[str, Any]:
        amount = validate_amount(monto)
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM sesiones WHERE id = ?",
                (sesion_id,),
            ).fetchone()
            if row is None:
                raise SessionNotFoundError(f"Sesión {sesion_id} no encontrada")
            if row["estado"] != SessionStatus.ACTIVE.value:
                raise InvalidSessionStateError(f"La sesión {sesion_id} ya está '{row['estado']}'")

            entry = datetime.strptime(row["hora_entrada"], DATETIME_FORMAT)
            exit_time = (
                datetime.strptime(hora_salida_fija, DATETIME_FORMAT)
                if hora_salida_fija is not None
                else self._clock()
            )
            if minutos_fijos is None:
                minutes = elapsed_minutes(entry, exit_time)
            elif isinstance(minutos_fijos, bool) or not isinstance(minutos_fijos, int):
                raise ValidationError("Los minutos deben ser un entero")
            elif minutos_fijos < 1:
                raise ValidationError("Los minutos deben ser mayores que cero")
            else:
                minutes = minutos_fijos

            if exit_time < entry:
                raise ValidationError("La salida no puede ser anterior a la entrada")

            cursor = connection.execute(
                """
                UPDATE sesiones
                SET hora_salida = ?, minutos_total = ?, monto = ?, estado = 'cobrado'
                WHERE id = ? AND estado = 'activo'
                """,
                (exit_time.strftime(DATETIME_FORMAT), minutes, amount, sesion_id),
            )
            if cursor.rowcount != 1:
                raise InvalidSessionStateError("La sesión cambió mientras se procesaba")
            updated = connection.execute(
                "SELECT * FROM sesiones WHERE id = ?",
                (sesion_id,),
            ).fetchone()

        result = self._row_to_dict(updated)
        if result is None:
            raise RuntimeError("No se pudo recuperar la sesión cobrada")
        return result

    def cancelar_sesion(self, sesion_id: int) -> None:
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE sesiones SET estado = 'cancelado'
                WHERE id = ? AND estado = 'activo'
                """,
                (sesion_id,),
            )
            if cursor.rowcount == 1:
                return
            row = connection.execute(
                "SELECT estado FROM sesiones WHERE id = ?",
                (sesion_id,),
            ).fetchone()
            if row is None:
                raise SessionNotFoundError(f"Sesión {sesion_id} no encontrada")
            raise InvalidSessionStateError(
                f"La sesión ya está '{row['estado']}' y no se puede cancelar"
            )

    def contar_activos(self) -> int:
        row = (
            self._conn()
            .execute("SELECT COUNT(*) AS total FROM sesiones WHERE estado = 'activo'")
            .fetchone()
        )
        return int(row["total"])

    @staticmethod
    def _date_bounds(fecha_inicio: str, fecha_fin: str) -> tuple[str, str]:
        try:
            start = date.fromisoformat(fecha_inicio)
            end = date.fromisoformat(fecha_fin)
        except (TypeError, ValueError) as exc:
            raise ValidationError("Las fechas deben usar el formato AAAA-MM-DD") from exc
        if end < start:
            raise ValidationError("La fecha final no puede ser anterior a la inicial")
        return (
            datetime.combine(start, datetime.min.time()).strftime(DATETIME_FORMAT),
            datetime.combine(end + timedelta(days=1), datetime.min.time()).strftime(
                DATETIME_FORMAT
            ),
        )

    def get_resumen_rango(self, fecha_inicio: str, fecha_fin: str) -> dict[str, Any]:
        start, end = self._date_bounds(fecha_inicio, fecha_fin)
        row = (
            self._conn()
            .execute(
                """
            SELECT
                COUNT(*) AS total_vehiculos,
                COUNT(CASE WHEN estado = 'cobrado' THEN 1 END) AS cobrados,
                COUNT(CASE WHEN estado = 'cancelado' THEN 1 END) AS cancelados,
                COUNT(CASE WHEN estado = 'activo' THEN 1 END) AS activos_ahora,
                COALESCE(SUM(CASE WHEN estado = 'cobrado' THEN monto END), 0) AS ingresos,
                COALESCE(AVG(CASE WHEN estado = 'cobrado' THEN minutos_total END), 0)
                    AS prom_minutos
            FROM sesiones
            WHERE hora_entrada >= ? AND hora_entrada < ?
            """,
                (start, end),
            )
            .fetchone()
        )
        return dict(row)

    def get_ingresos_por_hora(self, fecha: str) -> list[dict[str, Any]]:
        start, end = self._date_bounds(fecha, fecha)
        rows = (
            self._conn()
            .execute(
                """
            SELECT
                strftime('%H', hora_entrada) AS hora,
                COUNT(*) AS vehiculos,
                COALESCE(SUM(monto), 0) AS ingresos
            FROM sesiones
            WHERE estado = 'cobrado' AND hora_entrada >= ? AND hora_entrada < ?
            GROUP BY strftime('%H', hora_entrada)
            ORDER BY hora
            """,
                (start, end),
            )
            .fetchall()
        )
        return [dict(row) for row in rows]

    def get_ingresos_por_dia(
        self,
        fecha_inicio: str,
        fecha_fin: str,
    ) -> list[dict[str, Any]]:
        start, end = self._date_bounds(fecha_inicio, fecha_fin)
        rows = (
            self._conn()
            .execute(
                """
            SELECT
                DATE(hora_entrada) AS fecha,
                COUNT(*) AS vehiculos,
                COALESCE(SUM(monto), 0) AS ingresos
            FROM sesiones
            WHERE estado = 'cobrado' AND hora_entrada >= ? AND hora_entrada < ?
            GROUP BY DATE(hora_entrada)
            ORDER BY fecha
            """,
                (start, end),
            )
            .fetchall()
        )
        return [dict(row) for row in rows]

    def get_ingresos_por_mes_en_año(self, año: int) -> list[dict[str, Any]]:
        if isinstance(año, bool) or not isinstance(año, int) or not 1 <= año <= 9998:
            raise ValidationError("El año no es válido")
        rows = (
            self._conn()
            .execute(
                """
            SELECT
                strftime('%m', hora_entrada) AS mes,
                COUNT(*) AS vehiculos,
                COALESCE(SUM(monto), 0) AS ingresos
            FROM sesiones
            WHERE estado = 'cobrado'
              AND hora_entrada >= ? AND hora_entrada < ?
            GROUP BY strftime('%m', hora_entrada)
            ORDER BY mes
            """,
                (f"{año:04d}-01-01 00:00:00", f"{año + 1:04d}-01-01 00:00:00"),
            )
            .fetchall()
        )
        return [dict(row) for row in rows]

    def get_por_tipo_rango(
        self,
        fecha_inicio: str,
        fecha_fin: str,
    ) -> list[dict[str, Any]]:
        start, end = self._date_bounds(fecha_inicio, fecha_fin)
        rows = (
            self._conn()
            .execute(
                """
            SELECT
                tipo_vehiculo,
                COUNT(*) AS cantidad,
                COALESCE(SUM(monto), 0) AS ingresos
            FROM sesiones
            WHERE estado = 'cobrado' AND hora_entrada >= ? AND hora_entrada < ?
            GROUP BY tipo_vehiculo
            ORDER BY cantidad DESC, tipo_vehiculo
            """,
                (start, end),
            )
            .fetchall()
        )
        return [dict(row) for row in rows]

    def get_historial_rango_count(self, fecha_inicio: str, fecha_fin: str) -> int:
        start, end = self._date_bounds(fecha_inicio, fecha_fin)
        row = (
            self._conn()
            .execute(
                """
            SELECT COUNT(*) AS total FROM sesiones
            WHERE estado != 'activo' AND hora_entrada >= ? AND hora_entrada < ?
            """,
                (start, end),
            )
            .fetchone()
        )
        return int(row["total"])

    @staticmethod
    def _validate_pagination(limit: int, offset: int) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise ValidationError("El límite debe ser un entero no negativo")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValidationError("El desplazamiento debe ser un entero no negativo")

    def get_historial_rango(
        self,
        fecha_inicio: str,
        fecha_fin: str,
        limit: int = 30,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        self._validate_pagination(limit, offset)
        if limit == 0:
            return []
        start, end = self._date_bounds(fecha_inicio, fecha_fin)
        rows = (
            self._conn()
            .execute(
                """
            SELECT * FROM sesiones
            WHERE estado != 'activo' AND hora_entrada >= ? AND hora_entrada < ?
            ORDER BY hora_entrada DESC, id DESC
            LIMIT ? OFFSET ?
            """,
                (start, end, limit, offset),
            )
            .fetchall()
        )
        return [dict(row) for row in rows]

    def get_historial(
        self,
        limit: int = 100,
        offset: int = 0,
        fecha: str | None = None,
        placa: str | None = None,
    ) -> list[dict[str, Any]]:
        self._validate_pagination(limit, offset)
        if limit == 0:
            return []

        conditions = ["estado != 'activo'"]
        params: list[Any] = []
        if fecha:
            start, end = self._date_bounds(fecha, fecha)
            conditions.append("hora_entrada >= ? AND hora_entrada < ?")
            params.extend((start, end))
        if placa:
            conditions.append("placa LIKE ?")
            params.append(f"%{placa.strip().upper()}%")
        params.extend((limit, offset))

        rows = (
            self._conn()
            .execute(
                f"""
            SELECT * FROM sesiones
            WHERE {" AND ".join(conditions)}
            ORDER BY hora_entrada DESC, id DESC
            LIMIT ? OFFSET ?
            """,
                params,
            )
            .fetchall()
        )
        return [dict(row) for row in rows]

    def get_totales_globales(self) -> dict[str, Any]:
        row = (
            self._conn()
            .execute(
                """
            SELECT
                COUNT(CASE WHEN estado = 'cobrado' THEN 1 END) AS total_sesiones,
                COUNT(CASE WHEN estado = 'cancelado' THEN 1 END) AS canceladas,
                COUNT(*) AS total_ingresaron,
                COALESCE(SUM(CASE WHEN estado = 'cobrado' THEN monto END), 0)
                    AS ingresos_totales,
                COALESCE(MAX(CASE WHEN estado = 'cobrado' THEN monto END), 0)
                    AS ticket_maximo
            FROM sesiones
            """
            )
            .fetchone()
        )
        return dict(row)
