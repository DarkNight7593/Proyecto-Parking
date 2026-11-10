"""Fachadas de los casos de uso consumidos por la presentación."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .ports import ReportExporter, SessionRepository


class ParkingService:
    """Operaciones diarias del estacionamiento."""

    def __init__(self, repository: SessionRepository):
        self._repository = repository

    def registrar_entrada(
        self, placa: str, tipo_vehiculo: str, observaciones: str = ""
    ) -> dict[str, Any]:
        return self._repository.registrar_entrada(placa, tipo_vehiculo, observaciones)

    def get_sesiones_activas(self) -> list[dict[str, Any]]:
        return self._repository.get_sesiones_activas()

    def cobrar_sesion(
        self,
        sesion_id: int,
        monto: float,
        minutos_fijos: int | None = None,
        hora_salida_fija: str | None = None,
    ) -> dict[str, Any]:
        return self._repository.cobrar_sesion(
            sesion_id,
            monto,
            minutos_fijos=minutos_fijos,
            hora_salida_fija=hora_salida_fija,
        )

    def cancelar_sesion(self, sesion_id: int) -> None:
        self._repository.cancelar_sesion(sesion_id)

    def contar_activos(self) -> int:
        return self._repository.contar_activos()

    def cerrar_conexion_actual(self) -> None:
        self._repository.cerrar_conexion_actual()


class ReportService:
    """Consultas financieras y exportación de reportes."""

    def __init__(self, repository: SessionRepository, exporter: ReportExporter):
        self._repository = repository
        self._exporter = exporter

    def get_resumen_rango(self, fecha_inicio: str, fecha_fin: str) -> dict[str, Any]:
        return self._repository.get_resumen_rango(fecha_inicio, fecha_fin)

    def get_ingresos_por_hora(self, fecha: str) -> list[dict[str, Any]]:
        return self._repository.get_ingresos_por_hora(fecha)

    def get_ingresos_por_dia(self, fecha_inicio: str, fecha_fin: str) -> list[dict[str, Any]]:
        return self._repository.get_ingresos_por_dia(fecha_inicio, fecha_fin)

    def get_ingresos_por_mes_en_año(self, año: int) -> list[dict[str, Any]]:
        return self._repository.get_ingresos_por_mes_en_año(año)

    def get_por_tipo_rango(self, fecha_inicio: str, fecha_fin: str) -> list[dict[str, Any]]:
        return self._repository.get_por_tipo_rango(fecha_inicio, fecha_fin)

    def get_historial_rango_count(self, fecha_inicio: str, fecha_fin: str) -> int:
        return self._repository.get_historial_rango_count(fecha_inicio, fecha_fin)

    def get_historial_rango(
        self,
        fecha_inicio: str,
        fecha_fin: str,
        limit: int = 30,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return self._repository.get_historial_rango(
            fecha_inicio,
            fecha_fin,
            limit=limit,
            offset=offset,
        )

    def exportar_excel(self, ruta: str | Path) -> None:
        self._exporter.exportar(ruta)

    def cerrar_conexion_actual(self) -> None:
        self._repository.cerrar_conexion_actual()
