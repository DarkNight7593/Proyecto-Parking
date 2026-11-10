from __future__ import annotations

from datetime import datetime

import pytest

from parkingpro.domain.errors import ValidationError
from parkingpro.domain.parking import (
    calculate_amount,
    elapsed_minutes,
    format_duration,
    validate_amount,
    validate_plate,
    validate_vehicle_type,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("abc-123", "ABC-123"), ("  xy9  ", "XY9"), ("A1", "A1")],
)
def test_validate_plate_normalizes_valid_values(raw, expected):
    assert validate_plate(raw) == expected


@pytest.mark.parametrize("plate", ["", "A", "ABC_123", "-ABC", "ABC-", "ABC--123"])
def test_validate_plate_rejects_invalid_values(plate):
    with pytest.raises(ValidationError):
        validate_plate(plate)


def test_validate_vehicle_type_rejects_unknown_values():
    assert validate_vehicle_type(" Auto ") == "Auto"
    with pytest.raises(ValidationError):
        validate_vehicle_type("Patinete")


def test_calculate_amount_applies_grace_and_rounds_started_hours():
    assert calculate_amount(15, 2.5, free_minutes=15) == 0.0
    assert calculate_amount(16, 2.5, free_minutes=15) == 2.5
    assert calculate_amount(136, 2.5, free_minutes=15) == 7.5


@pytest.mark.parametrize("amount", [-1, float("nan"), float("inf"), "texto"])
def test_validate_amount_rejects_unsafe_values(amount):
    with pytest.raises(ValidationError):
        validate_amount(amount)


def test_duration_helpers_cover_boundaries():
    start = datetime(2026, 11, 10, 8, 0)
    assert elapsed_minutes(start, datetime(2026, 11, 10, 8, 0, 30)) == 1
    assert format_duration(65) == "1h 05min"
