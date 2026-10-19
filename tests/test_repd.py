from pathlib import Path

import pandas as pd
import pytest

from gbeg.ingest import repd

HEADER = (
    "Ref ID,Site Name,Operator (or Applicant),Technology Type,Installed Capacity (MWelec),"
    "Development Status (short),Are they re-applying (New REPD Ref),Post Code,County,Region,"
    "Country,X-coordinate,Y-coordinate,Record Last Updated (dd/mm/yyyy)\r\n"
)

ROWS = [
    # normal English site, latin-1 character, embedded newline in name
    (
        '1,"Caf\xe9 Farm\nSolar",Op A,Solar Photovoltaics,5,Operational,,M1 1AA,'
        "Greater Manchester,North West,England ,383800,398000,01/02/2026"
    ),
    # Scottish site with easting/northing swapped beyond the grid edge
    (
        "2,Tarland Substation,Op B,Battery,49.9,Awaiting Construction,,,Aberdeenshire,Scotland,"
        "Scotland,807158,352561,01/02/2026"
    ),
    # Scottish site swapped but still inside the grid
    (
        "3,Bolfornought Farm,Op C,Battery,20,Application Submitted,,,Stirling,Scotland,"
        "Scotland,693597,282277,01/02/2026"
    ),
    # offshore beyond the grid edge
    (
        "4,Big Array,Op D,Wind Offshore,1800,Operational,,,Norfolk,Offshore,England,"
        "708047,312194,01/02/2026"
    ),
    # whitespace-only capacity, missing coordinates, superseded by record 6
    "5,Old Scheme,Op E,Wind Onshore,   ,Revised,6,,Cumbria,North West,England,,,01/02/2026",
    (
        "6,New Scheme,Op E,Wind Onshore,12,Application Submitted,,,Cumbria,North West,England,"
        "330000,520000,01/02/2026"
    ),
]


@pytest.fixture
def repd_csv(tmp_path: Path) -> Path:
    path = tmp_path / "repd.csv"
    path.write_bytes((HEADER + "\r\n".join(ROWS) + "\r\n").encode("latin-1"))
    return path


@pytest.fixture
def staged(repd_csv):
    return repd.stage(repd_csv).set_index("source_record_id")


def test_cleans_text(staged):
    assert staged.loc["1", "site_name"] == "Café Farm Solar"
    assert staged.loc["1", "country_raw"] == "England"


def test_maps_categories(staged):
    assert staged.loc["1", "technology"] == "solar_pv"
    assert staged.loc["2", "lifecycle_stage"] == "consented"
    assert staged.loc["5", "lifecycle_stage"] == "superseded"
    assert staged.loc["5", "superseded_by"] == "6"


def test_blank_capacity_is_null(staged):
    assert staged.loc["5", "capacity_mw"] != staged.loc["5", "capacity_mw"]  # NaN
    assert staged.loc["2", "capacity_mw"] == pytest.approx(49.9)


@pytest.mark.parametrize("ref", ["2", "3"])
def test_swapped_scottish_coordinates_are_fixed(staged, ref):
    row = staged.loc[ref]
    assert row["location_flag"] == repd.FLAG_SWAPPED
    assert row["northing"] > repd.SCOTLAND_MIN_NORTHING
    assert row["latitude"] > 55


def test_offshore_kept_and_flagged(staged):
    assert staged.loc["4", "location_flag"] == repd.FLAG_OFFSHORE
    assert staged.loc["4", "easting"] == 708047


def test_missing_coordinates_flagged(staged):
    assert staged.loc["5", "location_flag"] == repd.FLAG_MISSING
    assert staged.loc["5", "location_quality"] == "missing"


def test_normal_row_unflagged(staged):
    assert pd.isna(staged.loc["1", "location_flag"])
    assert staged.loc["1", "latitude"] == pytest.approx(53.48, abs=0.01)


def test_unmapped_technology_fails_loudly(tmp_path):
    path = tmp_path / "bad.csv"
    bad = ROWS[0].replace("Solar Photovoltaics", "Cold Fusion")
    path.write_bytes((HEADER + bad + "\r\n").encode("latin-1"))
    with pytest.raises(repd.UnmappedValueError, match="Cold Fusion"):
        repd.stage(path)


def test_writes_duckdb(staged, repd_csv, tmp_path):
    rows = repd.write_duckdb(repd.stage(repd_csv), tmp_path / "t.duckdb")
    assert rows == len(staged)


REAL = Path(__file__).resolve().parents[1] / "data/raw/repd/2026-Q2/REPD_Publication_Q2_2026.csv"


@pytest.mark.skipif(not REAL.exists(), reason="real REPD extract not downloaded")
def test_real_extract_quality_gates():
    df = repd.stage(REAL)
    assert df["source_record_id"].is_unique
    onshore = df[df["location_flag"] != repd.FLAG_OFFSHORE]
    assert onshore["easting"].dropna().between(0, 700_000).all()
    assert onshore["northing"].dropna().between(0, 1_300_000).all()
    assert df["technology"].notna().all()
    assert df["lifecycle_stage"].notna().all()
