"""Screening rules, driven by config/screening.yaml. Each function returns its answer and a
plain-English reason so results can be explained."""

from __future__ import annotations

import math
from pathlib import Path

import yaml

DEFAULT_CONFIG = Path(__file__).resolve().parents[3] / "config" / "screening.yaml"

URBAN, BORDERLINE, RURAL = "Urban", "Borderline", "Rural"


def load_config(path: Path = DEFAULT_CONFIG) -> dict:
    return yaml.safe_load(Path(path).read_text())


def ons_group(ruc_name: str | None) -> str | None:
    """Collapse the six ONS 2021 classes to urban / rural."""
    if not ruc_name:
        return None
    return "urban" if ruc_name.strip().lower().startswith("urban") else "rural"


def setting(ruc_name: str | None, addresses_in_radius: int | None,
            nearest_m: float | None, cfg: dict) -> tuple[str | None, str]:
    rules = cfg["setting"]
    r = rules["radius_m"]
    group = ons_group(ruc_name)
    if group is None and addresses_in_radius is None:
        return None, "Not assessed: rural/urban and address data not loaded"
    if group is None:
        return None, "Not assessed: ONS rural/urban classification not loaded"
    if addresses_in_radius is None:
        return None, "Not assessed: address data not loaded"

    urban = rules["urban_if"]
    if group == "urban" and urban.get("ons_urban", True):
        return URBAN, f"ONS classes the area as {ruc_name}"
    if addresses_in_radius >= urban["addresses_at_least"]:
        return URBAN, (f"{addresses_in_radius} addresses within {r} m, although ONS classes "
                       f"the area as {ruc_name}")

    rural = rules["rural_if"]
    reasons = []
    if addresses_in_radius >= rural["addresses_below"]:
        reasons.append(f"{addresses_in_radius} addresses within {r} m")
    if nearest_m is not None and nearest_m < rural["nearest_address_at_least_m"]:
        reasons.append(f"nearest address only {nearest_m:.0f} m away")
    if not reasons:
        return RURAL, (f"ONS: {ruc_name}; {addresses_in_radius} addresses within {r} m, "
                       f"nearest {nearest_m:.0f} m")
    return BORDERLINE, f"ONS classes it rural, but {' and '.join(reasons)}"


def assumed_level(kva: float | None, cfg: dict) -> float | None:
    if kva is None:
        return None
    for upper, level in cfg["noise"]["assumed_level_by_kva"]:
        if kva <= upper:
            return float(level)
    return float(cfg["noise"]["assumed_level_by_kva"][-1][1])


def predicted_level(level_ref: float, distance_m: float, cfg: dict) -> float:
    """Point source, free field: L = Lref - 20 log10(d / dref). Cautious (no screening)."""
    d_ref = cfg["noise"]["reference_distance_m"]
    d = max(distance_m, d_ref)
    return round(level_ref - 20 * math.log10(d / d_ref), 1)


def background(setting_name: str | None, period: str, cfg: dict) -> tuple[float, str]:
    table = cfg["noise"]["assumed_night_background_db"]
    key = (setting_name or BORDERLINE).lower()
    level = float(table[key])
    note = "" if setting_name else " (setting unknown, borderline value used)"
    if period == "day":
        level += cfg["noise"]["day_uplift_db"]
    return level, note


def impact(excess: float, cfg: dict) -> tuple[str, str]:
    label = next(lbl for threshold, lbl in cfg["noise"]["impact_bands"] if excess >= threshold)
    rag_cfg = cfg["noise"]["rag"]
    rag = ("Red" if excess >= rag_cfg["red_at_least"]
           else "Amber" if excess >= rag_cfg["amber_at_least"] else "Green")
    return label, rag


def normalise_period(value: object) -> str:
    text = str(value or "").strip().lower()
    if text.startswith("day"):
        return "day"
    return "night"  # night, 24h, continuous or blank: assess the more sensitive period
