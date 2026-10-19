from pathlib import Path

import pandas as pd
import pytest

from gbeg.ingest import ecr_enwl

COLUMNS = [
    "Customer Name ", "Customer Site ", "Postcode ", "County ",
    "Location (X-coordinate):\nEastings (where data is held)",
    "Location (y-coordinate):\nNorthings (where data is held)",
    "Grid Supply Point", "Bulk Supply Point", "Primary",
    "Point of Connection (POC)\nVoltage (kV)", "Licence Area ",
    "Energy Source 1", "Energy Conversion Technology 1",
    "Energy Source & Energy Conversion Technology 1 - Registered Capacity (MW)",
    "Connection Status ", "Already connected Registered Capacity (MW) ",
    "Maximum Export Capacity (MW)", "Accepted to Connect Registered Capacity (MW)",
    "Change to Maximum Export Capacity (MW) ", "Date Connected", "Date Accepted",
    "Last Updated",
]

ROWS = [
    # connected solar: capacity from the "already connected" column
    ["Op A", "Clifton Marsh", "PR4 1AA", "Lancashire", "340000", "430000", "GSP", "BSP",
     "PRI", "33", "ELECTRICITY NORTH WEST LIMITED", "SOLAR", "PHOTOVOLTAIC", "49.9",
     "CONNECTED", "49.9", "45", "", "", "2016-01-01", "", "2024-03-14"],
    # accepted battery with the 99.9 value and a misspelt source label
    ["Op B", "Sale BESS", "M33 1AA", "Greater Manchester", "378000", "392000", "GSP",
     "BSP", "DATA NOT AVAILABLE", "132", "SPENWL",
     "STORED ENERGY (ALL STORED ENERGY IRRESPECTVE OF THE ORIGINAL ENERGY SOURCE)",
     "STORAGE - ELECTROCHEMICAL  (BATTERIES)", "99.9", "ACCEPTED TO CONNECT", "0.0",
     "0.0", "99.9", "99.9", "", "2021-11-10", "2021-12-06"],
    # hybrid and a repeated identical record
    ["Op C", "Low Dyke", "CA11 9PS", "Cumbria", "346152", "538804", "-", "-", "-", "11",
     "ELECTRICITY NORTH WEST PLC", "BATTERY & SOLAR", "PV & BESS", "6",
     "ACCEPTED TO CONNECT", "0", "0", "6", "6", "", "2017-08-03", "2023-04-05"],
    ["Op C", "Low Dyke", "CA11 9PS", "Cumbria", "346152", "538804", "-", "-", "-", "11",
     "ELECTRICITY NORTH WEST PLC", "BATTERY & SOLAR", "PV & BESS", "6",
     "ACCEPTED TO CONNECT", "0", "0", "6", "6", "", "2017-08-03", "2023-04-05"],
    # no fuel stated at all
    ["Op D", "Mystery", "BB1 1AA", "Lancashire", "370000", "428000", "-", "-", "-", "11",
     "ELECTRICITY NORTH WEST LIMITED", "DATA NOT AVAILABLE", "", "2",
     "CONNECTED", "2", "2", "", "", "2010-01-01", "", "2024-03-14"],
]


def _write(path: Path, rows) -> Path:
    pd.DataFrame(rows, columns=COLUMNS).to_csv(path, index=False, encoding="utf-8-sig")
    return path


@pytest.fixture
def staged(tmp_path):
    return ecr_enwl.stage(_write(tmp_path / "ecr.csv", ROWS))


def test_technology_rules(staged):
    assert staged["technology"].tolist() == [
        "solar_pv", "battery_storage", "hybrid", "hybrid", "other"
    ]


def test_capacity_follows_connection_status(staged):
    assert staged.loc[0, "capacity_mw"] == pytest.approx(49.9)
    assert staged.loc[0, "export_capacity_mw"] == pytest.approx(45)
    assert staged.loc[1, "capacity_mw"] == pytest.approx(99.9)
    assert staged.loc[1, "capacity_flag"] == ecr_enwl.FLAG_99_9
    assert pd.isna(staged.loc[0, "capacity_flag"])


def test_sentinels_become_null(staged):
    assert pd.isna(staged.loc[1, "primary_substation"])
    assert pd.isna(staged.loc[2, "grid_supply_point"])


def test_lifecycle(staged):
    assert staged["lifecycle_stage"].tolist()[:2] == ["operational", "consented"]


def test_ids_unique_and_repeats_flagged(staged):
    assert staged["source_record_id"].is_unique
    assert staged["possible_duplicate"].tolist() == [False, False, True, True, False]


def test_ids_are_deterministic(tmp_path):
    a = ecr_enwl.stage(_write(tmp_path / "a.csv", ROWS))["source_record_id"]
    b = ecr_enwl.stage(_write(tmp_path / "b.csv", ROWS))["source_record_id"]
    assert a.tolist() == b.tolist()


def test_unclassifiable_technology_fails(tmp_path):
    bad = [ROWS[0][:11] + ["COLD FUSION", "REACTOR"] + ROWS[0][13:]]
    with pytest.raises(ecr_enwl.UnmappedValueError, match="COLD FUSION"):
        ecr_enwl.stage(_write(tmp_path / "bad.csv", bad))
