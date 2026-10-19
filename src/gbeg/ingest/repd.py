"""Stage the DESNZ Renewable Energy Planning Database (REPD) into the common record shape.

Known quirks of the published CSV (see docs/decision-log.md for counts):
- Latin-1 encoded, CRLF line endings, and newlines embedded inside quoted fields,
  including inside the coordinate columns.
- Whitespace-only cells and trailing spaces in categorical values ("England ").
- A handful of Scottish sites have easting and northing swapped.
- Some rows carry the wrong Country/Region label while their coordinates are correct,
  so location is always taken from the coordinates, never the label.
- Re-applications create a chain of records for one site; the old record points at the
  new one through "Are they re-applying (New REPD Ref)".
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import yaml

from gbeg.transform.coords import InvalidLocationError, from_en

SOURCE = "repd"
CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"

# Southern tip of mainland Scotland is roughly northing 530 km.
SCOTLAND_MIN_NORTHING = 530_000

LIFECYCLE = {
    "Operational": "operational",
    "Under Construction": "under_construction",
    "Awaiting Construction": "consented",
    "Application Submitted": "in_planning",
    "Appeal Lodged": "in_planning",
    "Application Refused": "inactive",
    "Application Withdrawn": "inactive",
    "Appeal Refused": "inactive",
    "Appeal Withdrawn": "inactive",
    "Abandoned": "inactive",
    "Planning Permission Expired": "inactive",
    "Decommissioned": "decommissioned",
    "Revised": "superseded",
    "No Application Required": "other",
}

FLAG_SWAPPED = "coords_swapped"
FLAG_OFFSHORE = "offshore"
FLAG_MISSING = "coords_missing"
FLAG_INVALID = "coords_invalid"


class UnmappedValueError(ValueError):
    """Raised when the source contains a category value with no mapping."""


def load_technology_map(source: str = SOURCE, config_dir: Path = CONFIG_DIR) -> dict[str, str]:
    data = yaml.safe_load((config_dir / "technology_map.yaml").read_text())
    mapping = data[source]
    unknown = set(mapping.values()) - set(data["enum"])
    if unknown:
        raise ValueError(f"technology_map.yaml maps to values not in enum: {sorted(unknown)}")
    return mapping


def read_raw(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="latin-1", dtype=str, keep_default_na=False)
    df.columns = [" ".join(c.split()) for c in df.columns]
    # Collapse embedded newlines and runs of whitespace; blank becomes null.
    df = df.apply(lambda s: s.str.split().str.join(" "))
    return df.replace("", None)


def _locate(x: str | None, y: str | None, region: str | None) -> tuple:
    """Return (easting, northing, lat, lon, flag) for one REPD row."""
    if x is None or y is None:
        return None, None, None, None, FLAG_MISSING
    try:
        e, n = float(x.replace(",", "")), float(y.replace(",", ""))
    except ValueError:
        return None, None, None, None, FLAG_INVALID

    if region == "Offshore":
        # Offshore sites can lie beyond the 700 km grid edge; keep them, but flag.
        return round(e), round(n), None, None, FLAG_OFFSHORE

    flag = None
    if region == "Scotland" and n < SCOTLAND_MIN_NORTHING and e >= SCOTLAND_MIN_NORTHING:
        e, n, flag = n, e, FLAG_SWAPPED
    try:
        loc = from_en(e, n)
    except InvalidLocationError:
        if 0 <= n <= 700_000 and 0 <= e <= 1_300_000:
            loc, flag = from_en(n, e), FLAG_SWAPPED
        else:
            return None, None, None, None, FLAG_INVALID
    return loc.easting, loc.northing, loc.latitude, loc.longitude, flag


def stage(path: Path, config_dir: Path = CONFIG_DIR) -> pd.DataFrame:
    raw = read_raw(path)
    tech_map = load_technology_map(config_dir=config_dir)

    unmapped_tech = sorted(set(raw["Technology Type"].dropna()) - set(tech_map))
    unmapped_status = sorted(set(raw["Development Status (short)"].dropna()) - set(LIFECYCLE))
    if unmapped_tech or unmapped_status:
        raise UnmappedValueError(
            f"Unmapped technology: {unmapped_tech}; unmapped status: {unmapped_status}"
        )

    located = [
        _locate(x, y, r)
        for x, y, r in zip(raw["X-coordinate"], raw["Y-coordinate"], raw["Region"], strict=True)
    ]
    loc = pd.DataFrame(
        located, columns=["easting", "northing", "latitude", "longitude", "location_flag"]
    )

    capacity = pd.to_numeric(
        raw["Installed Capacity (MWelec)"].str.replace(",", ""), errors="coerce"
    )

    staged = pd.DataFrame(
        {
            "source": SOURCE,
            "source_record_id": raw["Ref ID"],
            "site_name": raw["Site Name"],
            "operator": raw["Operator (or Applicant)"],
            "technology_raw": raw["Technology Type"],
            "technology": raw["Technology Type"].map(tech_map),
            "capacity_mw": capacity,
            "lifecycle_raw": raw["Development Status (short)"],
            "lifecycle_stage": raw["Development Status (short)"].map(LIFECYCLE),
            "superseded_by": raw["Are they re-applying (New REPD Ref)"],
            "postcode": raw["Post Code"],
            "county_raw": raw["County"],
            "region_raw": raw["Region"],
            "country_raw": raw["Country"],
            "record_updated": pd.to_datetime(
                raw["Record Last Updated (dd/mm/yyyy)"], format="%d/%m/%Y", errors="coerce"
            ).dt.date,
        }
    )
    staged = pd.concat([staged, loc], axis=1)
    staged["location_quality"] = staged["easting"].notna().map(
        {True: "coordinates", False: "missing"}
    )
    return staged


def write_duckdb(df: pd.DataFrame, db_path: Path, table: str = "stg_repd") -> int:
    import duckdb

    db_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(db_path)) as con:
        con.register("staged", df)
        con.execute(f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM staged")
        return con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage an REPD CSV into DuckDB")
    parser.add_argument("csv", type=Path)
    parser.add_argument("--db", type=Path, default=Path("data/processed/gbeg.duckdb"))
    args = parser.parse_args()
    df = stage(args.csv)
    rows = write_duckdb(df, args.db)
    print(f"stg_repd: {rows} rows")
    print(df["location_flag"].value_counts(dropna=False).to_string())


if __name__ == "__main__":
    main()
