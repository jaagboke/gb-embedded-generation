"""Export the app dataset: one row per ENWL ECR record with its REPD comparison.

The app reads only this file, so it deploys without the raw sources or the pipeline.
Match rules are translated into plain-English statuses for non-specialist viewers.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import pandas as pd

from gbeg import pipeline

MATCH_STATUS = {
    "matched_name": "In both registers",
    "matched_location": "In both registers",
    "weak_candidate": "Possible match",
    "capacity_mismatch": "Not found in REPD",
    "nearby_other_technology": "Not found in REPD",
    None: "Not found in REPD",
}
MATCH_BASIS = {
    "matched_name": "Site names agree",
    "matched_location": "Within 1 km, same technology and similar capacity",
    "weak_candidate": "Same technology 1-2 km away, names differ",
    "capacity_mismatch": "Nearest same-technology site has a very different capacity",
    "nearby_other_technology": "Only other technologies nearby",
    None: "No REPD site within 2 km",
}
FOSSIL_STATUS = "Fossil (not covered by REPD)"

TECHNOLOGY_LABELS = {
    "solar_pv": "Solar PV",
    "onshore_wind": "Onshore wind",
    "offshore_wind": "Offshore wind",
    "battery_storage": "Battery storage",
    "other_storage": "Other storage",
    "pumped_storage": "Pumped storage",
    "hydro": "Hydro",
    "marine": "Marine",
    "biomass": "Biomass",
    "anaerobic_digestion": "Anaerobic digestion",
    "landfill_gas": "Landfill gas",
    "energy_from_waste": "Energy from waste",
    "hydrogen": "Hydrogen",
    "geothermal": "Geothermal",
    "fossil_gas": "Gas",
    "fossil_oil": "Oil / diesel",
    "hybrid": "Hybrid (e.g. solar + battery)",
    "other": "Other / unknown",
}
STATUS_LABELS = {
    "operational": "Operational",
    "under_construction": "Under construction",
    "consented": "Consented / awaiting construction",
    "in_planning": "In planning",
    "inactive": "Refused, withdrawn or expired",
    "decommissioned": "Decommissioned",
    "other": "Other",
}
ECR_STATUS_LABELS = {"operational": "Connected", "consented": "Accepted to connect"}

EXPORT_SQL = """
    SELECT
        e.source_record_id AS site_id,
        e.site_name, e.operator, e.technology, e.technology_raw, e.technology_family,
        e.capacity_mw, s.export_capacity_mw, s.capacity_flag, s.possible_duplicate,
        e.lifecycle_stage AS ecr_stage, s.connection_voltage_kv,
        s.grid_supply_point, s.bulk_supply_point, s.primary_substation,
        e.postcode, s.county_raw AS county, s.date_connected, s.date_accepted,
        e.latitude, e.longitude, e.easting, e.northing,
        m.match_rule, m.distance_m, m.name_similarity, m.capacity_ratio,
        r.source_record_id AS repd_ref, r.site_name AS repd_site_name,
        r.operator AS repd_operator, r.technology AS repd_technology,
        r.capacity_mw AS repd_capacity_mw, r.lifecycle_stage AS repd_stage,
        r.lifecycle_raw AS repd_status_raw, r.postcode AS repd_postcode,
        r.latitude AS repd_latitude, r.longitude AS repd_longitude
    FROM int_site_records e
    JOIN stg_ecr_enwl s ON s.source_record_id = e.source_record_id
    LEFT JOIN int_site_matches m ON m.ecr_id = e.source_record_id
    LEFT JOIN int_site_records r ON r.source_record_id = m.repd_id AND r.source = 'repd'
    WHERE e.source = 'ecr_enwl'
    ORDER BY e.capacity_mw DESC NULLS LAST
"""


def build_export(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    df = con.execute(EXPORT_SQL).df()
    fossil = df["technology_family"].eq("fossil")
    rule = df["match_rule"].where(df["match_rule"].notna(), None)

    df["match_status"] = rule.map(MATCH_STATUS).where(~fossil, FOSSIL_STATUS)
    df["match_basis"] = rule.map(MATCH_BASIS).where(~fossil, "REPD covers renewables and "
                                                             "storage only")
    # Only show REPD details where the pair is a match or a possible one.
    shown = df["match_status"].isin(["In both registers", "Possible match"])
    repd_cols = [c for c in df.columns if c.startswith("repd_")]
    df.loc[~shown, repd_cols] = None

    df["technology_label"] = df["technology"].map(TECHNOLOGY_LABELS)
    df["ecr_status"] = df["ecr_stage"].map(ECR_STATUS_LABELS)
    df["repd_status"] = df["repd_stage"].map(STATUS_LABELS)
    df["status_conflict"] = shown & df["ecr_stage"].eq("consented") & df["repd_stage"].eq(
        "inactive"
    )
    return df.drop(columns=["technology_family"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the app dataset")
    parser.add_argument("--db", type=Path, default=Path("data/processed/gbeg.duckdb"))
    parser.add_argument("--out", type=Path, default=Path("app/data/enwl_sites.csv"))
    args = parser.parse_args()
    with duckdb.connect(str(args.db)) as con:
        pipeline.build(con)
        df = build_export(con)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)
    print(f"Wrote {len(df)} sites to {args.out}")
    print(df["match_status"].value_counts().to_string())


if __name__ == "__main__":
    main()
