"""Smoke tests for the export and the Streamlit app."""

from pathlib import Path

import pandas as pd
import pytest

from gbeg import export, pipeline
from tests.test_pipeline import con  # noqa: F401  (reuse the synthetic pipeline fixture)

APP_DIR = Path(__file__).resolve().parents[1] / "app"
APP = APP_DIR / "streamlit_app.py"
DATA = APP_DIR / "data" / "enwl_sites.csv"


def _with_ecr_extras(con):  # noqa: F811
    """Add the ECR-only columns the export reads, which the pipeline fixture omits."""
    for col, kind in [("export_capacity_mw", "DOUBLE"), ("capacity_flag", "VARCHAR"),
                      ("possible_duplicate", "BOOLEAN"), ("connection_voltage_kv", "DOUBLE"),
                      ("grid_supply_point", "VARCHAR"), ("bulk_supply_point", "VARCHAR"),
                      ("primary_substation", "VARCHAR"), ("county_raw", "VARCHAR"),
                      ("date_connected", "DATE"), ("date_accepted", "DATE")]:
        con.execute(f"ALTER TABLE stg_ecr_enwl ADD COLUMN {col} {kind}")
    pipeline.build(con)
    return con


def test_export_statuses(con):  # noqa: F811
    df = export.build_export(_with_ecr_extras(con)).set_index("site_id")
    assert df.loc["e_close_named", "match_status"] == "In both registers"
    assert df.loc["e_weak", "match_status"] == "Possible match"
    assert df.loc["e_big", "match_status"] == "Not found in REPD"
    assert df.loc["e_gas", "match_status"] == export.FOSSIL_STATUS
    # REPD details are only shown for matches and possible matches
    assert pd.isna(df.loc["e_big", "repd_site_name"])
    assert df.loc["e_close_named", "repd_site_name"] == "Clifton Marsh Solar Farm"
    assert df["technology_label"].notna().all()


def test_app_opens_on_screening_page():
    st_testing = pytest.importorskip("streamlit.testing.v1")
    at = st_testing.AppTest.from_file(str(APP), default_timeout=90).run()
    assert not at.exception
    assert at.title[0].value == "Screen generator sites"
    assert any("sites screened" in s.value for s in at.subheader)


@pytest.mark.skipif(not DATA.exists(), reason="app dataset not exported")
def test_register_page_runs_and_filters():
    st_testing = pytest.importorskip("streamlit.testing.v1")
    at = st_testing.AppTest.from_file(str(APP_DIR / "views" / "register.py"),
                                      default_timeout=60).run()
    assert not at.exception
    at.sidebar.multiselect[1].set_value(["Possible match"]).run()
    assert not at.exception
    at.sidebar.text_input[0].set_value("no such site").run()
    assert not at.exception
    assert at.info  # empty-state message shown
