"""Run the full screening over a user's site list."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from gbeg.screening import rules
from gbeg.screening.inputs import ColumnMap, _num, detect_columns, locate_row
from gbeg.screening.layers import ReferenceData

RESULT_COLUMNS = [
    "Site", "Location given", "Located by", "Easting", "Northing", "Latitude", "Longitude",
    "ONS rural/urban class", "Addresses within 250 m", "Addresses within 500 m",
    "Nearest address (m)", "Setting", "Why this setting",
    "Rating (kVA)", "Noise at 7 m dB(A)", "Noise figure", "Assessed period",
    "Predicted at nearest address dB(A)", "Assumed background dB", "Excess over background dB",
    "Indicative noise impact", "RAG", "Generation within 2 km", "Generation within 2 km (MW)",
    "Nearest existing schemes", "Notes",
]


def _clean(value):
    """None for missing values, including the NaN pandas uses for empty numeric cells."""
    return None if value is None or (isinstance(value, float) and np.isnan(value)) else value


@dataclass
class ScreeningResult:
    results: pd.DataFrame
    problems: pd.DataFrame        # rows that could not be screened, with the reason
    columns: ColumnMap
    nearby: dict[int, pd.DataFrame]


def _location_text(row: pd.Series, cols: ColumnMap) -> str:
    parts = [str(row[c]) for role in ("location", "gridref", "postcode", "easting", "northing",
                                      "lat", "lon")
             if (c := cols.get(role)) and pd.notna(row.get(c)) and str(row.get(c))]
    return ", ".join(parts)


def _site_name(row: pd.Series, cols: ColumnMap, i: int) -> str:
    """The name column if there is one, else the location text (often a name or address)."""
    for role in ("name", "location"):
        col = cols.get(role)
        if col and pd.notna(row.get(col)) and str(row.get(col)).strip():
            return str(row.get(col)).strip()
    return f"Row {i + 2}"


def screen(sites: pd.DataFrame, ref: ReferenceData, cfg: dict,
           columns: ColumnMap | None = None) -> ScreeningResult:
    cols = columns or detect_columns(sites)
    region = cfg["region"]
    records, problems = [], []

    for i, row in sites.iterrows():
        name = _site_name(row, cols, i)
        loc = locate_row(row, cols, ref.postcode_lookup, ref.site_lookup)
        given = _location_text(row, cols)
        if loc.issue:
            problems.append({"Row": i + 2, "Site": name, "Location given": given,
                             "Problem": loc.issue})
            continue
        if not (region["easting"][0] <= loc.easting <= region["easting"][1]
                and region["northing"][0] <= loc.northing <= region["northing"][1]):
            problems.append({"Row": i + 2, "Site": name, "Location given": given,
                             "Problem": "Outside the area covered (North West England, "
                                        "Cheshire, Merseyside and North Wales)"})
            continue
        records.append({
            "_row": i, "Site": name, "Location given": given, "Located by": loc.method,
            "Easting": loc.easting, "Northing": loc.northing,
            "Latitude": loc.latitude, "Longitude": loc.longitude,
            "Rating (kVA)": _num(row.get(cols.get("kva"))) if cols.get("kva") else None,
            "_noise": _num(row.get(cols.get("noise_7m"))) if cols.get("noise_7m") else None,
            "Assessed period": rules.normalise_period(
                row.get(cols.get("period")) if cols.get("period") else None),
        })

    df = pd.DataFrame(records)
    nearby: dict[int, pd.DataFrame] = {}
    if df.empty:
        return ScreeningResult(pd.DataFrame(columns=RESULT_COLUMNS), pd.DataFrame(problems),
                               cols, nearby)

    xy = df[["Easting", "Northing"]].to_numpy(dtype=np.float64)
    radius = cfg["setting"]["radius_m"]
    df["ONS rural/urban class"] = ref.ruc(xy)
    addr = ref.addresses(xy, (radius, 500))
    df["Addresses within 250 m"] = addr[f"addresses_{radius}m"].to_numpy()
    df["Addresses within 500 m"] = addr["addresses_500m"].to_numpy()
    df["Nearest address (m)"] = addr["nearest_address_m"].to_numpy()

    gen_radius = cfg["nearby_generation"]["radius_m"]
    gen = ref.generation_near(xy, gen_radius)

    out = []
    for k, rec in enumerate(df.to_dict("records")):
        nearest = _clean(rec["Nearest address (m)"])
        nearest = None if nearest is None else float(nearest)
        count = _clean(rec["Addresses within 250 m"])
        count = None if count is None else int(count)
        rec["ONS rural/urban class"] = _clean(rec["ONS rural/urban class"])
        set_name, why = rules.setting(rec["ONS rural/urban class"], count, nearest, cfg)
        rec["Setting"], rec["Why this setting"] = set_name, why

        notes = []
        rec["Rating (kVA)"] = _clean(rec["Rating (kVA)"])
        level, source = _clean(rec.pop("_noise")), "from input file"
        if level is None:
            level = rules.assumed_level(rec["Rating (kVA)"], cfg)
            source = "assumed from kVA rating" if level is not None else None
        rec["Noise at 7 m dB(A)"], rec["Noise figure"] = level, source

        if level is not None and nearest is not None:
            pred = rules.predicted_level(level, nearest, cfg)
            bg, note = rules.background(set_name, rec["Assessed period"], cfg)
            excess = round(pred - bg, 1)
            label, rag = rules.impact(excess, cfg)
            rec.update({"Predicted at nearest address dB(A)": pred,
                        "Assumed background dB": bg, "Excess over background dB": excess,
                        "Indicative noise impact": label, "RAG": rag})
            if note:
                notes.append("Background" + note)
        else:
            rec.update({"Predicted at nearest address dB(A)": None,
                        "Assumed background dB": None, "Excess over background dB": None,
                        "Indicative noise impact": None, "RAG": None})
            if level is None:
                notes.append("No noise figure or kVA rating given")
            if nearest is None:
                notes.append("Address data not loaded, so noise not estimated")

        g = gen[k]
        if g is None:
            rec.update({"Generation within 2 km": None, "Generation within 2 km (MW)": None,
                        "Nearest existing schemes": None})
        else:
            nearby[rec["_row"]] = g
            rec["Generation within 2 km"] = len(g)
            rec["Generation within 2 km (MW)"] = round(float(g["mw"].fillna(0).sum()), 1)
            rec["Nearest existing schemes"] = "; ".join(
                f"{r.name} ({r.technology}, {r.distance_m:.0f} m)"
                for r in g.head(3).itertuples()) or "None within 2 km"
        rec["Notes"] = "; ".join(notes) or None
        out.append(rec)

    results = pd.DataFrame(out)
    results.index = results.pop("_row")
    return ScreeningResult(results[RESULT_COLUMNS], pd.DataFrame(problems), cols, nearby)
