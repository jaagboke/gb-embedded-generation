"""Stage the Electricity North West Embedded Capacity Register (>=1MW part).

Known quirks of the Opendatasoft export (see docs/decision-log.md for counts):
- UTF-8 with a byte-order mark; column headers contain embedded newlines.
- No usable record ID: "Reference" is blank on almost every row, and MPANs are mostly
  "DATA NOT AVAILABLE". A deterministic key is built from identifying fields instead.
- Several sentinels mean "unknown": "DATA NOT AVAILABLE", "TO BE CONFIRMED", "-".
- Technology labels are free text in upper case with typos and spacing variants, so they
  are classified by ordered regex rules (config/technology_map.yaml, `ecr_rules`).
- Capacity sits in different columns depending on connection status.
- 99.9 MW appears repeatedly on accepted-to-connect battery schemes. It may be a genuine
  "just under 100 MW" design or a placeholder, so it is kept and flagged for checking.
"""

from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path

import pandas as pd
import yaml

from gbeg.transform.coords import InvalidLocationError, from_en

SOURCE = "ecr_enwl"
DNO = "ENWL"
CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"

SENTINELS = {"", "DATA NOT AVAILABLE", "TO BE CONFIRMED", "-"}
LIFECYCLE = {"CONNECTED": "operational", "ACCEPTED TO CONNECT": "consented"}
FLAG_99_9 = "capacity_99_9_check"
KEY_FIELDS = [
    "Customer Site",
    "Postcode",
    "Location (X-coordinate): Eastings (where data is held)",
    "Location (y-coordinate): Northings (where data is held)",
    "Energy Conversion Technology 1",
    "Connection Status",
]

X_COL = "Location (X-coordinate): Eastings (where data is held)"
Y_COL = "Location (y-coordinate): Northings (where data is held)"
REG_CAP_1 = "Energy Source & Energy Conversion Technology 1 - Registered Capacity (MW)"


class UnmappedValueError(ValueError):
    """Raised when a technology or status cannot be classified."""


def load_rules(config_dir: Path = CONFIG_DIR) -> list[tuple[re.Pattern, str]]:
    data = yaml.safe_load((config_dir / "technology_map.yaml").read_text())
    rules = [(re.compile(r["pattern"]), r["technology"]) for r in data["ecr_rules"]]
    unknown = {t for _, t in rules} - set(data["enum"])
    if unknown:
        raise ValueError(f"ecr_rules map to values not in enum: {sorted(unknown)}")
    return rules


def classify(source: str | None, tech: str | None, rules) -> str | None:
    source = "" if pd.isna(source) else source
    tech = "" if pd.isna(tech) else tech
    text = f"{source} :: {tech}"
    for pattern, technology in rules:
        if pattern.search(text):
            return technology
    return None


def read_raw(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    df.columns = [" ".join(c.split()) for c in df.columns]
    df = df.apply(lambda s: s.str.split().str.join(" ").str.upper())
    return df.mask(df.isin(SENTINELS))


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def _positive(s: pd.Series) -> pd.Series:
    return s.where(s > 0)


def _record_ids(df: pd.DataFrame) -> pd.Series:
    """Deterministic ID from identifying fields, with an occurrence suffix for repeats."""
    base = df[KEY_FIELDS].fillna("").agg("|".join, axis=1)
    occurrence = base.groupby(base).cumcount().astype(str)
    return (base + "#" + occurrence).map(lambda s: hashlib.sha1(s.encode()).hexdigest()[:16])


def stage(path: Path, config_dir: Path = CONFIG_DIR) -> pd.DataFrame:
    raw = read_raw(path)
    rules = load_rules(config_dir)

    technology = [
        classify(s, t, rules)
        for s, t in zip(raw["Energy Source 1"], raw["Energy Conversion Technology 1"], strict=True)
    ]
    unmapped = raw.loc[pd.isna(pd.Series(technology)).values,
                       ["Energy Source 1", "Energy Conversion Technology 1"]]
    unmapped_status = sorted(set(raw["Connection Status"].dropna()) - set(LIFECYCLE))
    if len(unmapped) or unmapped_status:
        raise UnmappedValueError(
            f"Unclassified technology: {unmapped.drop_duplicates().values.tolist()}; "
            f"unmapped status: {unmapped_status}"
        )

    connected = raw["Connection Status"].eq("CONNECTED")
    reg1 = _positive(_num(raw[REG_CAP_1]))
    reg_connected = _positive(_num(raw["Already connected Registered Capacity (MW)"]))
    reg_accepted = _positive(_num(raw["Accepted to Connect Registered Capacity (MW)"]))
    status_cap = reg_connected.where(connected, reg_accepted)
    capacity = status_cap.fillna(reg1)
    basis = pd.Series("registered_capacity_by_status", index=raw.index)
    basis = basis.where(status_cap.notna(), "registered_capacity_technology_1")
    basis = basis.where(capacity.notna(), None)

    export = _positive(_num(raw["Maximum Export Capacity (MW)"])).where(
        connected, _positive(_num(raw["Change to Maximum Export Capacity (MW)"]))
    )
    flag = capacity.eq(99.9) | export.eq(99.9)

    locs = []
    for x, y in zip(raw[X_COL], raw[Y_COL], strict=True):
        try:
            loc = from_en(float(x), float(y))
            locs.append((loc.easting, loc.northing, loc.latitude, loc.longitude, None))
        except (TypeError, ValueError, InvalidLocationError):
            flag_ = "coords_missing" if x is None or y is None else "coords_invalid"
            locs.append((None, None, None, None, flag_))
    loc = pd.DataFrame(
        locs, columns=["easting", "northing", "latitude", "longitude", "location_flag"]
    )

    ids = _record_ids(raw)
    staged = pd.DataFrame(
        {
            "source": SOURCE,
            "source_record_id": ids,
            "dno": DNO,
            "site_name": raw["Customer Site"],
            "operator": raw["Customer Name"],
            "technology_raw": raw["Energy Source 1"].fillna("") + " :: "
            + raw["Energy Conversion Technology 1"].fillna(""),
            "technology": technology,
            "capacity_mw": capacity,
            "capacity_basis": basis,
            "export_capacity_mw": export,
            "capacity_flag": flag.map({True: FLAG_99_9, False: None}),
            "lifecycle_raw": raw["Connection Status"],
            "lifecycle_stage": raw["Connection Status"].map(LIFECYCLE),
            "connection_voltage_kv": _num(raw["Point of Connection (POC) Voltage (kV)"]),
            "grid_supply_point": raw["Grid Supply Point"],
            "bulk_supply_point": raw["Bulk Supply Point"],
            "primary_substation": raw["Primary"],
            "licence_area_raw": raw["Licence Area"],
            "postcode": raw["Postcode"],
            "county_raw": raw["County"],
            "date_connected": pd.to_datetime(raw["Date Connected"], errors="coerce").dt.date,
            "date_accepted": pd.to_datetime(raw["Date Accepted"], errors="coerce").dt.date,
            "record_updated": pd.to_datetime(raw["Last Updated"], errors="coerce").dt.date,
            "possible_duplicate": ids.index.isin(
                raw[raw.duplicated(KEY_FIELDS, keep=False)].index
            ),
        }
    )
    staged = pd.concat([staged, loc], axis=1)
    staged["location_quality"] = staged["easting"].notna().map(
        {True: "coordinates", False: "missing"}
    )
    return staged


def write_duckdb(df: pd.DataFrame, db_path: Path, table: str = "stg_ecr_enwl") -> int:
    import duckdb

    db_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(db_path)) as con:
        con.register("staged", df)
        con.execute(f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM staged")
        return con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage an ENWL ECR CSV into DuckDB")
    parser.add_argument("csv", type=Path)
    parser.add_argument("--db", type=Path, default=Path("data/processed/gbeg.duckdb"))
    args = parser.parse_args()
    df = stage(args.csv)
    print(f"stg_ecr_enwl: {write_duckdb(df, args.db)} rows")


if __name__ == "__main__":
    main()
