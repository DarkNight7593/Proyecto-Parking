"""Integración con impresoras de tickets."""

from .installer import PrinterInstaller
from .printer import Printer

__all__ = ["Printer", "PrinterInstaller"]
