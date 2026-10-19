"""Capacity normalisation to MW.

Sources mix kW, MW, kVA and MVA, and sometimes publish numbers as text with thousands
separators. Apparent power (VA) is converted assuming unity power factor and flagged,
because that assumption should be visible downstream rather than silently applied.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

_FACTORS_TO_MW = {
    "w": 1e-6,
    "kw": 1e-3,
    "mw": 1.0,
    "gw": 1e3,
}
_APPARENT = {"va": "w", "kva": "kw", "mva": "mw"}

FLAG_UNITY_PF = "apparent_power_assumed_unity_pf"


class InvalidCapacityError(ValueError):
    """Raised when a capacity value or unit cannot be interpreted."""


@dataclass(frozen=True)
class Capacity:
    mw: float | None
    flag: str | None = None


def _parse_number(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return None if isinstance(value, float) and math.isnan(value) else float(value)
    text = str(value).strip().replace(",", "")
    if text in {"", "-", "n/a", "N/A", "NA"}:
        return None
    try:
        return float(text)
    except ValueError as exc:
        raise InvalidCapacityError(f"Not a number: {value!r}") from exc


def to_mw(value: object, unit: str) -> Capacity:
    """Convert a capacity in the given unit to MW.

    Returns Capacity(mw=None) for blank values. Negative values are rejected because export
    capacity cannot be negative; import-only storage should be modelled separately.
    """
    number = _parse_number(value)
    if number is None:
        return Capacity(None)
    if number < 0:
        raise InvalidCapacityError(f"Negative capacity: {value!r}")

    key = unit.strip().lower()
    flag = None
    if key in _APPARENT:
        key = _APPARENT[key]
        flag = FLAG_UNITY_PF
    if key not in _FACTORS_TO_MW:
        raise InvalidCapacityError(f"Unknown capacity unit: {unit!r}")

    return Capacity(round(number * _FACTORS_TO_MW[key], 6), flag)
