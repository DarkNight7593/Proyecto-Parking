from pathlib import Path
from unittest.mock import Mock

from parkingpro.application import ParkingService, ReportService


def test_parking_service_delegates_use_case_to_repository():
    repository = Mock()
    repository.registrar_entrada.return_value = {"id": 1, "placa": "ABC-123"}
    service = ParkingService(repository)

    result = service.registrar_entrada("ABC-123", "Auto")

    assert result["id"] == 1
    repository.registrar_entrada.assert_called_once_with("ABC-123", "Auto", "")


def test_report_service_hides_exporter_from_presentation(tmp_path):
    repository = Mock()
    exporter = Mock()
    service = ReportService(repository, exporter)
    destination = tmp_path / "reporte.xlsx"

    service.exportar_excel(destination)

    exporter.exportar.assert_called_once_with(Path(destination))
