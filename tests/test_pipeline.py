import duckdb
import pandas as pd
import pytest

from gbeg import pipeline


def _record(source, rid, tech, name, cap, e, n, stage="operational", flag=None):
    return {
        "source": source, "source_record_id": rid, "site_name": name, "operator": None,
        "technology": tech, "technology_raw": tech, "capacity_mw": cap,
        "lifecycle_stage": stage, "lifecycle_raw": stage, "postcode": None,
        "easting": e, "northing": n, "latitude": None, "longitude": None,
        "location_quality": "coordinates", "location_flag": flag,
    }


@pytest.fixture
def con():
    con = duckdb.connect()
    repd = pd.DataFrame([
        _record("repd", "r_solar", "solar_pv", "Clifton Marsh Solar Farm", 10.0, 350_000, 450_000),
        _record("repd", "r_wind", "onshore_wind", "Oldside Wind Farm", 5.0, 360_000, 460_000),
        _record("repd", "r_old", "solar_pv", "Old Scheme", 10.0, 370_000, 470_000,
                stage="superseded"),
        _record("repd", "r_far", "solar_pv", "Roanhead", 4.0, 390_000, 491_500),
        _record("repd", "r_other", "solar_pv", "Bleabeck", 4.0, 400_000, 500_800),
    ])
    ecr = pd.DataFrame([
        _record("ecr_enwl", "e_close_named", "solar_pv", "CLIFTON MARSH", 9.0, 350_200, 450_100),
        _record("ecr_enwl", "e_big", "onshore_wind", "OLDSIDE", 50.0, 360_100, 460_000),
        _record("ecr_enwl", "e_wrong_tech", "battery_storage", "TOWN LANE BESS", 5.0,
                350_300, 450_000),
        _record("ecr_enwl", "e_superseded_only", "solar_pv", "OLD SCHEME", 10.0,
                370_000, 470_000),
        _record("ecr_enwl", "e_gas", "fossil_gas", "GAS PEAKER", 2.0, 380_000, 480_000),
        _record("ecr_enwl", "e_named_far", "solar_pv", "ROANHEAD SOLAR FARM", 4.0,
                390_000, 490_000),
        _record("ecr_enwl", "e_close_unnamed", "solar_pv", "KENYON WAY", 4.0, 400_000, 500_000),
        _record("ecr_enwl", "e_weak", "solar_pv", "HELLRIGG", 4.0, 400_000, 502_000),
    ]).assign(dno="ENWL")
    con.register("repd_df", repd)
    con.register("ecr_df", ecr)
    con.execute("CREATE TABLE stg_repd AS SELECT * FROM repd_df")
    con.execute("CREATE TABLE stg_ecr_enwl AS SELECT * FROM ecr_df")
    pipeline.build(con)
    return con


def _rule(con, ecr_id):
    row = con.execute(
        "SELECT match_rule FROM int_site_matches WHERE ecr_id = ?", [ecr_id]
    ).fetchone()
    return row[0] if row else None


@pytest.mark.parametrize(
    ("ecr_id", "rule"),
    [
        ("e_close_named", "matched_name"),
        ("e_named_far", "matched_name"),         # 1.5 km apart but the names agree
        ("e_close_unnamed", "matched_location"),  # 800 m, names disagree
        ("e_weak", "weak_candidate"),             # 1.2 km, names disagree
        ("e_big", "capacity_mismatch"),
        ("e_wrong_tech", "nearby_other_technology"),
        ("e_superseded_only", None),
    ],
)
def test_match_rules(con, ecr_id, rule):
    assert _rule(con, ecr_id) == rule


def test_fossil_reported_out_of_scope(con):
    outcomes = {(s, o): n for s, o, n, _ in pipeline.summary(con)}
    assert outcomes[("fossil (outside REPD scope)", "not_applicable")] == 1
    assert outcomes[("REPD-eligible", "matched_name")] == 2
