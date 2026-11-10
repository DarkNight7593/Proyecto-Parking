"""Reglas de negocio independientes de la interfaz y la persistencia."""

from .parking import (
    DATETIME_FORMAT,
    MAX_PLATE_LENGTH,
    MIN_PLATE_LENGTH,
    SUPPORTED_VEHICLE_TYPES,
    SessionStatus,
    calculate_amount,
    elapsed_minutes,
    format_duration,
    normalize_plate,
    validate_plate,
    validate_vehicle_type,
)

__all__ = [
    "DATETIME_FORMAT",
    "MAX_PLATE_LENGTH",
    "MIN_PLATE_LENGTH",
    "SUPPORTED_VEHICLE_TYPES",
    "SessionStatus",
    "calculate_amount",
    "elapsed_minutes",
    "format_duration",
    "normalize_plate",
    "validate_plate",
    "validate_vehicle_type",
]
