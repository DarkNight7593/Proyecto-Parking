"""Errores conocidos del dominio."""


class ParkingError(ValueError):
    """Error de negocio que puede mostrarse al operador."""


class ValidationError(ParkingError):
    """Un dato recibido no cumple las reglas del negocio."""


class DuplicateActiveSessionError(ParkingError):
    """La placa ya tiene una sesión activa."""


class SessionNotFoundError(ParkingError):
    """La sesión solicitada no existe."""


class InvalidSessionStateError(ParkingError):
    """La operación no está permitida para el estado actual."""
