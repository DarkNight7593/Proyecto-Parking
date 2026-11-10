"""Punto de composición de dependencias de ParkingPro."""

from parkingpro.application import ParkingService, ReportService
from parkingpro.infrastructure import ConfigManager, Database
from parkingpro.infrastructure.printing import Printer, PrinterInstaller
from parkingpro.infrastructure.reporting import ExcelExporter
from parkingpro.presentation.app import ParkingProApp


def build_app() -> ParkingProApp:
    """Construye la aplicación con sus adaptadores concretos."""
    config = ConfigManager()
    repository = Database(config.get_db_path())
    repository.inicializar()
    parking_service = ParkingService(repository)
    report_service = ReportService(
        repository,
        ExcelExporter(repository, config),
    )
    printer = Printer(config.get_nombre_impresora())

    return ParkingProApp(
        config=config,
        parking_service=parking_service,
        report_service=report_service,
        printer=printer,
        printer_factory=Printer,
        installer_factory=PrinterInstaller,
    )


def main() -> None:
    app = build_app()
    app.mainloop()
