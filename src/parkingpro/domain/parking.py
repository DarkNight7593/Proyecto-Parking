"""Reglas puras del negocio de estacionamiento."""

from __future__ import annotations

import math
import re
from datetime import datetime
from decimal import ROUND_UP, Decimal, InvalidOperation
from enum import StrEnum

from .errors import ValidationError

DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
MIN_PLATE_LENGTH = 2
MAX_PLATE_LENGTH = 10
SUPPORTED_VEHICLE_TYPES = (
    "Auto",
    "Moto",
    "Camioneta",
    "Bus",
    "Camión",
    "Bicicleta",
)
_PLATE_PATTERN = re.compile(r"^[A-Z0-9]+(?:-[A-Z0-9]+)*$")


class SessionStatus(StrEnum):
    ACTIVE = "activo"
    PAID = "cobrado"
    CANCELLED = "cancelado"


def normalize_plate(value: str) -> str:
    """Normaliza una placa para comparar y persistir siempre el mismo valor."""
    if not isinstance(value, str):
        raise ValidationError("La placa debe ser texto")
    return value.strip().upper()


def validate_plate(value: str) -> str:
    """Valida y devuelve la placa normalizada."""
    plate = normalize_plate(value)
    if len(plate) < MIN_PLATE_LENGTH:
        raise ValidationError(f"La placa debe tener al menos {MIN_PLATE_LENGTH} caracteres")
    if len(plate) > MAX_PLATE_LENGTH:
        raise ValidationError(f"La placa no puede superar {MAX_PLATE_LENGTH} caracteres")
    if not _PLATE_PATTERN.fullmatch(plate):
        raise ValidationError("La placa solo admite letras, números y guiones internos")
    return plate


def validate_vehicle_type(value: str) -> str:
    """Valida un tipo configurado por ParkingPro."""
    if not isinstance(value, str):
        raise ValidationError("El tipo de vehículo debe ser texto")
    normalized = value.strip()
    if normalized not in SUPPORTED_VEHICLE_TYPES:
        raise ValidationError(f"Tipo de vehículo no válido: {normalized or '(vacío)'}")
    return normalized


def _decimal_non_negative(value: object, field_name: str) -> Decimal:
    if isinstance(value, bool):
        raise ValidationError(f"{field_name} debe ser un número")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError(f"{field_name} debe ser un número válido") from exc
    if not number.is_finite() or number < 0:
        raise ValidationError(f"{field_name} no puede ser negativo ni infinito")
    return number


def validate_amount(value: object) -> float:
    """Valida un importe y lo redondea a dos decimales."""
    amount = _decimal_non_negative(value, "El monto")
    return float(amount.quantize(Decimal("0.01")))


def calculate_amount(minutes: int, hourly_rate: float, free_minutes: int = 0) -> float:
    """Cobra por cada hora iniciada después del período de gracia."""
    if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes < 0:
        raise ValidationError("Los minutos deben ser un entero no negativo")
    if isinstance(free_minutes, bool) or not isinstance(free_minutes, int) or free_minutes < 0:
        raise ValidationError("El tiempo libre debe ser un entero no negativo")

    rate = _decimal_non_negative(hourly_rate, "La tarifa")
    billable_minutes = max(0, minutes - free_minutes)
    if billable_minutes == 0:
        return 0.0

    hours = (Decimal(billable_minutes) / Decimal(60)).to_integral_value(rounding=ROUND_UP)
    return float((hours * rate).quantize(Decimal("0.01")))


def elapsed_minutes(start: datetime, end: datetime) -> int:
    """Devuelve minutos transcurridos, con un mínimo operativo de un minuto."""
    if end < start:
        raise ValidationError("La salida no puede ser anterior a la entrada")
    return max(1, math.floor((end - start).total_seconds() / 60))


def format_duration(minutes: int) -> str:
    """Convierte minutos a una representación breve y legible."""
    if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes < 0:
        raise ValidationError("Los minutos deben ser un entero no negativo")
    hours, remaining = divmod(minutes, 60)
    return f"{hours}h {remaining:02d}min" if hours else f"{remaining}min"
