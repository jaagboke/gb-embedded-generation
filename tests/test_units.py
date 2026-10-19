import math

import pytest

from gbeg.transform.units import FLAG_UNITY_PF, InvalidCapacityError, to_mw


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [
        (5, "MW", 5.0),
        (500, "kW", 0.5),
        ("1,250", "kW", 1.25),
        (" 49.9 ", "mw", 49.9),
        (2, "GW", 2000.0),
    ],
)
def test_real_power_units(value, unit, expected):
    result = to_mw(value, unit)
    assert result.mw == pytest.approx(expected)
    assert result.flag is None


def test_apparent_power_is_flagged():
    result = to_mw(1000, "kVA")
    assert result.mw == pytest.approx(1.0)
    assert result.flag == FLAG_UNITY_PF


@pytest.mark.parametrize("blank", [None, "", "-", "N/A", math.nan])
def test_blank_values_return_none(blank):
    assert to_mw(blank, "MW").mw is None


@pytest.mark.parametrize(("value", "unit"), [(-1, "MW"), ("abc", "MW"), (5, "horsepower")])
def test_invalid_inputs_raise(value, unit):
    with pytest.raises(InvalidCapacityError):
        to_mw(value, unit)
