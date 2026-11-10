"""Configuración persistente de ParkingPro."""

from __future__ import annotations

import configparser
import math
import os
import sys
import tempfile
import threading
import unicodedata
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path

from platformdirs import user_data_path

from parkingpro.domain.errors import ValidationError


def _application_directory() -> Path:
    custom_directory = os.environ.get("PARKINGPRO_DATA_DIR")
    if custom_directory:
        return Path(custom_directory).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    project_directory = Path(__file__).resolve().parents[3]
    if (project_directory / "pyproject.toml").is_file():
        return project_directory
    return Path(user_data_path("ParkingPro", ensure_exists=True))


class ConfigManager:
    """Lee y guarda la configuración local de forma atómica."""

    DEFAULT_CONFIG = {
        "negocio": {
            "nombre": "Mi Estacionamiento",
            "direccion": "",
            "telefono": "",
            "ruc": "",
        },
        "impresora": {
            "nombre": "",
            "activa": "True",
            "papel_mm": "80",
        },
        "sistema": {
            "version": "1.1.0",
            "db_path": "parkingpro.db",
            "moneda": "S/",
            "tiempo_libre_min": "0",
        },
        "tarifas": {
            "auto": "2.0",
            "moto": "1.5",
            "camioneta": "3.0",
            "bus": "5.0",
            "camion": "5.0",
            "bicicleta": "1.0",
        },
    }
    TIPOS_CLAVE = tuple(DEFAULT_CONFIG["tarifas"])

    def __init__(self, config_path: str | os.PathLike[str] | None = None):
        self.config_path = Path(config_path or _application_directory() / "config.ini")
        self.config = configparser.ConfigParser()
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        with self._lock:
            changed = not self.config_path.exists()
            if self.config_path.exists():
                self.config.read(self.config_path, encoding="utf-8")

            for section, values in self.DEFAULT_CONFIG.items():
                if not self.config.has_section(section):
                    self.config.add_section(section)
                    changed = True
                for key, value in values.items():
                    if not self.config.has_option(section, key):
                        self.config.set(section, key, value)
                        changed = True

            if changed:
                self._save()

    def _save(self) -> None:
        """Reemplaza el archivo completo para no dejarlo parcialmente escrito."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.config_path.name}.",
            suffix=".tmp",
            dir=self.config_path.parent,
            text=True,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                self.config.write(file)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_name, self.config_path)
        except Exception:
            with suppress(FileNotFoundError):
                os.unlink(temporary_name)
            raise

    def get(self, section: str, key: str, fallback: str | None = None) -> str:
        with self._lock:
            return self.config.get(section, key, fallback=fallback)

    def set(self, section: str, key: str, value: object) -> None:
        self.set_many({section: {key: str(value)}})

    def set_many(self, updates: Mapping[str, Mapping[str, object]]) -> None:
        """Aplica varias opciones con una sola escritura en disco."""
        with self._lock:
            for section, values in updates.items():
                if not self.config.has_section(section):
                    self.config.add_section(section)
                for key, value in values.items():
                    self.config.set(section, key, str(value))
            self._save()

    def getbool(self, section: str, key: str, fallback: bool = False) -> bool:
        with self._lock:
            try:
                return self.config.getboolean(section, key, fallback=fallback)
            except ValueError:
                return fallback

    def getfloat(self, section: str, key: str, fallback: float = 0.0) -> float:
        with self._lock:
            try:
                value = self.config.getfloat(section, key, fallback=fallback)
                return value if math.isfinite(value) else fallback
            except (TypeError, ValueError):
                return fallback

    def getint(self, section: str, key: str, fallback: int = 0) -> int:
        with self._lock:
            try:
                return self.config.getint(section, key, fallback=fallback)
            except (TypeError, ValueError):
                return fallback

    def get_nombre_negocio(self) -> str:
        return self.get("negocio", "nombre", fallback="Mi Estacionamiento").strip()

    def get_nombre_impresora(self) -> str:
        return self.get(
            "impresora",
            "nombre",
            fallback="TicketeraEstacionamiento",
        ).strip()

    def get_moneda(self) -> str:
        return self.get("sistema", "moneda", fallback="S/").strip() or "S/"

    def get_tiempo_libre(self) -> int:
        return max(0, self.getint("sistema", "tiempo_libre_min", fallback=0))

    @staticmethod
    def _normalizar_clave(vehicle_type: str) -> str:
        normalized = unicodedata.normalize("NFKD", vehicle_type.strip().lower())
        without_accents = "".join(char for char in normalized if not unicodedata.combining(char))
        return without_accents.replace(" ", "_")

    def get_tarifa(self, vehicle_type: str) -> float:
        key = self._normalizar_clave(vehicle_type)
        return max(0.0, self.getfloat("tarifas", key, fallback=2.0))

    def set_tarifa(self, vehicle_type: str, price: float) -> None:
        if isinstance(price, bool) or not math.isfinite(price) or price < 0:
            raise ValidationError("La tarifa debe ser un número no negativo")
        self.set("tarifas", self._normalizar_clave(vehicle_type), f"{price:.2f}")

    def get_all_tarifas(self) -> dict[str, float]:
        return {key: self.get_tarifa(key) for key in self.TIPOS_CLAVE}

    def get_db_path(self) -> str:
        configured_path = Path(
            self.get("sistema", "db_path", fallback="parkingpro.db").strip() or "parkingpro.db"
        ).expanduser()
        if not configured_path.is_absolute():
            configured_path = self.config_path.parent / configured_path
        return str(configured_path.resolve())

    def get_datos_negocio(self) -> dict[str, str]:
        return {
            "nombre": self.get("negocio", "nombre", fallback=""),
            "direccion": self.get("negocio", "direccion", fallback=""),
            "telefono": self.get("negocio", "telefono", fallback=""),
            "ruc": self.get("negocio", "ruc", fallback=""),
        }

    def set_datos_negocio(
        self,
        nombre: str,
        direccion: str,
        telefono: str,
        ruc: str,
    ) -> None:
        self.set_many(
            {
                "negocio": {
                    "nombre": nombre.strip(),
                    "direccion": direccion.strip(),
                    "telefono": telefono.strip(),
                    "ruc": ruc.strip(),
                }
            }
        )
