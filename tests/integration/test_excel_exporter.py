from __future__ import annotations

from openpyxl import load_workbook

from parkingpro.infrastructure.reporting import ExcelExporter


class ReportConfig:
    def get_moneda(self):
        return "S/"

    def get_nombre_negocio(self):
        return "Parking de prueba"


def test_export_creates_readable_workbook_with_session_and_chart(db, tmp_path):
    session = db.registrar_entrada("ABC-123", "Auto")
    db.cobrar_sesion(
        session["id"],
        5,
        minutos_fijos=90,
        hora_salida_fija="2026-11-10 12:00:00",
    )
    output = tmp_path / "reporte.xlsx"

    ExcelExporter(db, ReportConfig()).exportar(output)

    workbook = load_workbook(output)
    worksheet = workbook["Sesiones"]
    values = [cell.value for row in worksheet.iter_rows() for cell in row]
    assert workbook.sheetnames == ["Sesiones"]
    assert session["ticket_numero"] in values
    assert "ABC-123" in values
    assert len(worksheet._charts) == 1
    workbook.close()
