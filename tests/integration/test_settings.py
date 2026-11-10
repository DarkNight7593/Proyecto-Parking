from __future__ import annotations

from pathlib import Path

import pytest

from parkingpro.domain.errors import ValidationError
from parkingpro.infrastructure.settings import ConfigManager


def test_config_creates_defaults_and_resolves_database_next_to_config(tmp_path):
    config_path = tmp_path / "config.ini"
    config = ConfigManager(config_path)

    assert config_path.exists()
    assert config.get_nombre_negocio() == "Mi Estacionamiento"
    assert Path(config.get_db_path()) == (tmp_path / "parkingpro.db").resolve()
    assert config.get_nombre_impresora() == ""
    assert config.getbool("impresora", "activa") is True
    assert config.getint("impresora", "papel_mm") == 80


def test_business_data_is_persisted_as_one_group(tmp_path):
    config_path = tmp_path / "config.ini"
    config = ConfigManager(config_path)
    config.set_datos_negocio(" Parking Lima ", " Av. Uno ", " 999 ", " 123 ")

    reloaded = ConfigManager(config_path)
    assert reloaded.get_datos_negocio() == {
        "nombre": "Parking Lima",
        "direccion": "Av. Uno",
        "telefono": "999",
        "ruc": "123",
    }


def test_tariff_key_supports_accents_and_rejects_negative_values(tmp_path):
    config = ConfigManager(tmp_path / "config.ini")
    config.set_tarifa("Camión", 7.25)
    assert config.get_tarifa("Camión") == 7.25

    with pytest.raises(ValidationError):
        config.set_tarifa("Auto", -1)
