from __future__ import annotations

from datetime import datetime

import pytest

from parkingpro.infrastructure.database import Database

FIXED_NOW = datetime(2026, 11, 10, 10, 30)


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "parkingpro_test.db", clock=lambda: FIXED_NOW)
    database.inicializar()
    try:
        yield database
    finally:
        database.close()
