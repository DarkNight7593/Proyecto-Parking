"""Contratos que separan los casos de uso de la infraestructura."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class SessionRepository(Protocol):
    def registrar_entrada(
        self, placa: str, tipo_vehiculo: str, observaciones: str = ""
    ) -> dict[str, Any]: ...

    def get_sesiones_activas(self) -> list[dict[str, Any]]: ...

    def cobrar_sesion(
        self,
        sesion_id: int,
        monto: float,
        minutos_fijos: int | None = None,
        hora_salida_fija: str | None = None,
    ) -> dict[str, Any]: ...

    def cancelar_sesion(self, sesion_id: int) -> None: ...

    def contar_activos(self) -> int: ...

    def get_resumen_rango(self, fecha_inicio: str, fecha_fin: str) -> dict[str, Any]: ...

    def get_ingresos_por_hora(self, fecha: str) -> list[dict[str, Any]]: ...

    def get_ingresos_por_dia(self, fecha_inicio: str, fecha_fin: str) -> list[dict[str, Any]]: ...

    def get_ingresos_por_mes_en_año(self, año: int) -> list[dict[str, Any]]: ...

    def get_por_tipo_rango(self, fecha_inicio: str, fecha_fin: str) -> list[dict[str, Any]]: ...

    def get_historial_rango_count(self, fecha_inicio: str, fecha_fin: str) -> int: ...

    def get_historial_rango(
        self,
        fecha_inicio: str,
        fecha_fin: str,
        limit: int = 30,
        offset: int = 0,
    ) -> list[dict[str, Any]]: ...

    def cerrar_conexion_actual(self) -> None: ...


class ReportExporter(Protocol):
    def exportar(self, ruta: str | Path) -> None: ...
