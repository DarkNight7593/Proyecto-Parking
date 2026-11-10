from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest

from parkingpro.domain.errors import (
    DuplicateActiveSessionError,
    InvalidSessionStateError,
    ValidationError,
)
from parkingpro.infrastructure.database import Database

FIXED_NOW = datetime(2026, 11, 10, 10, 30)


def test_register_charge_and_report_session(db):
    session = db.registrar_entrada("abc-123", "Auto", "Cliente frecuente")
    paid = db.cobrar_sesion(
        session["id"],
        5.5,
        minutos_fijos=90,
        hora_salida_fija="2026-11-10 12:00:00",
    )

    assert paid["placa"] == "ABC-123"
    assert paid["estado"] == "cobrado"
    assert paid["monto"] == 5.5
    summary = db.get_resumen_rango("2026-11-10", "2026-11-10")
    assert summary["cobrados"] == 1
    assert summary["ingresos"] == 5.5


def test_duplicate_plate_and_second_close_are_rejected(db):
    session = db.registrar_entrada("ABC-123", "Auto")
    with pytest.raises(DuplicateActiveSessionError):
        db.registrar_entrada(" abc-123 ", "Moto")

    db.cancelar_sesion(session["id"])
    with pytest.raises(InvalidSessionStateError):
        db.cancelar_sesion(session["id"])


@pytest.mark.parametrize("plate", ["", "A", "ABC_123", "ABCDEFGHIJK"])
def test_database_enforces_plate_rules_without_ui(db, plate):
    with pytest.raises(ValidationError):
        db.registrar_entrada(plate, "Auto")


def test_database_rejects_unknown_vehicle_type(db):
    with pytest.raises(ValidationError):
        db.registrar_entrada("ABC-123", "Patinete")


def test_invalid_amount_and_exit_time_do_not_modify_session(db):
    session = db.registrar_entrada("ABC-123", "Auto")
    with pytest.raises(ValidationError):
        db.cobrar_sesion(session["id"], float("nan"))
    with pytest.raises(ValidationError):
        db.cobrar_sesion(
            session["id"],
            2,
            hora_salida_fija="2026-11-10 09:00:00",
        )
    assert db.get_sesion_por_id(session["id"])["estado"] == "activo"


def test_history_pagination_and_date_validation(db):
    for index in range(3):
        session = db.registrar_entrada(f"ABC-12{index}", "Auto")
        db.cancelar_sesion(session["id"])

    page = db.get_historial_rango("2026-11-10", "2026-11-10", limit=2, offset=1)
    assert len(page) == 2
    assert db.get_historial_rango_count("2026-11-10", "2026-11-10") == 3
    assert db.get_historial_rango("2026-11-10", "2026-11-10", limit=0) == []

    with pytest.raises(ValidationError):
        db.get_resumen_rango("2026-11-11", "2026-11-10")


def test_concurrent_registration_keeps_one_active_session(tmp_path):
    path = tmp_path / "concurrent.db"
    initializer = Database(path, clock=lambda: FIXED_NOW)
    initializer.inicializar()
    initializer.close()

    def register_once():
        worker_db = Database(path, clock=lambda: FIXED_NOW)
        try:
            return worker_db.registrar_entrada("ABC-123", "Auto")
        finally:
            worker_db.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [executor.submit(register_once) for _ in range(2)]

    successes = 0
    duplicates = 0
    for result in results:
        try:
            result.result()
            successes += 1
        except DuplicateActiveSessionError:
            duplicates += 1

    assert (successes, duplicates) == (1, 1)


def test_ticket_sequence_is_stable(db):
    first = db.registrar_entrada("AAA-111", "Auto")
    second = db.registrar_entrada("BBB-222", "Moto")
    assert first["ticket_numero"] == "TK202611100001"
    assert second["ticket_numero"] == "TK202611100002"


def test_financial_queries_and_filters_are_consistent(db):
    auto = db.registrar_entrada("AAA-111", "Auto")
    moto = db.registrar_entrada("BBB-222", "Moto")
    db.cobrar_sesion(
        auto["id"],
        5,
        minutos_fijos=60,
        hora_salida_fija="2026-11-10 11:30:00",
    )
    db.cobrar_sesion(
        moto["id"],
        3,
        minutos_fijos=30,
        hora_salida_fija="2026-11-10 11:00:00",
    )

    assert db.get_sesion_activa_por_placa("AAA-111") is None
    assert db.get_ingresos_por_hora("2026-11-10") == [
        {"hora": "10", "vehiculos": 2, "ingresos": 8.0}
    ]
    assert db.get_ingresos_por_dia("2026-11-01", "2026-11-30") == [
        {"fecha": "2026-11-10", "vehiculos": 2, "ingresos": 8.0}
    ]
    assert db.get_ingresos_por_mes_en_año(2026) == [{"mes": "11", "vehiculos": 2, "ingresos": 8.0}]
    by_type = db.get_por_tipo_rango("2026-11-10", "2026-11-10")
    assert {row["tipo_vehiculo"] for row in by_type} == {"Auto", "Moto"}
    assert db.get_historial(placa="AAA") == [db.get_sesion_por_id(auto["id"])]

    totals = db.get_totales_globales()
    assert totals["total_sesiones"] == 2
    assert totals["ingresos_totales"] == 8.0
