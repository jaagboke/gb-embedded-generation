"""Turn the large national downloads into small regional reference files for the app.

    python -m gbeg.screening.prepare ruc        <ONS OA boundaries + RUC: .gpkg/.shp/.geojson/.zip>
    python -m gbeg.screening.prepare addresses  <OS Open UPRN .csv or .zip>
    python -m gbeg.screening.prepare postcodes  <OS Code-Point Open .zip or folder>
    python -m gbeg.screening.prepare generation [--db data/processed/gbeg.duckdb]

Each step clips to the region in config/screening.yaml and writes to app/data/reference.
"""

from __future__ import annotations

import argparse
import io
import re
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from gbeg.screening.rules import load_config

OUT = Path("app/data/reference")


def _bbox(cfg: dict) -> tuple[int, int, int, int]:
    (e0, e1), (n0, n1) = cfg["region"]["easting"], cfg["region"]["northing"]
    return e0, n0, e1, n1


def _pick(columns, *patterns) -> str:
    for pattern in patterns:
        for c in columns:
            if re.fullmatch(pattern, str(c), flags=re.IGNORECASE):
                return c
    raise KeyError(f"None of {patterns} found in columns {list(columns)}")


# ---- ONS output areas with rural/urban class ------------------------------------------
def prepare_ruc(path: Path, out: Path = OUT, cfg: dict | None = None) -> int:
    import geopandas as gpd
    import shapely

    cfg = cfg or load_config()
    gdf = gpd.read_file(path)
    oa = _pick(gdf.columns, r"OA21CD", r"OA\d*CD")
    ruc = _pick(gdf.columns, r"RUC21NM", r"RUC\d*NM", r"RUC.*NAME", r"RUC.*DESC")
    if gdf.crs is None or gdf.crs.to_epsg() != 27700:
        gdf = gdf.to_crs(27700)
    e0, n0, e1, n1 = _bbox(cfg)
    gdf = gdf.cx[e0:e1, n0:n1]
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({
        "oa21cd": gdf[oa].astype(str).to_numpy(),
        "ruc21nm": gdf[ruc].astype(str).to_numpy(),
        "wkb": shapely.to_wkb(gdf.geometry.to_numpy()),
    }).to_parquet(out / "ruc_oa.parquet", index=False)
    return len(gdf)


# ---- OS Open UPRN ----------------------------------------------------------------------
def _open_csv(path: Path):
    if path.suffix.lower() == ".zip":
        z = zipfile.ZipFile(path)
        name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        return z.open(name)
    return open(path, "rb")


def prepare_addresses(path: Path, out: Path = OUT, cfg: dict | None = None,
                      chunksize: int = 2_000_000) -> int:
    cfg = cfg or load_config()
    e0, n0, e1, n1 = _bbox(cfg)
    parts = []
    with _open_csv(Path(path)) as fh:
        header = pd.read_csv(fh, nrows=0).columns
        fh.seek(0) if hasattr(fh, "seek") and fh.seekable() else None
    x_col = _pick(header, r"X_COORDINATE", r"EASTING", r"X")
    y_col = _pick(header, r"Y_COORDINATE", r"NORTHING", r"Y")
    with _open_csv(Path(path)) as fh:
        for chunk in pd.read_csv(fh, usecols=[x_col, y_col], chunksize=chunksize):
            x, y = chunk[x_col].to_numpy(), chunk[y_col].to_numpy()
            keep = (x >= e0) & (x <= e1) & (y >= n0) & (y <= n1)
            parts.append(pd.DataFrame({"x": np.round(x[keep]).astype(np.int32),
                                       "y": np.round(y[keep]).astype(np.int32)}))
    df = pd.concat(parts, ignore_index=True)
    out.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out / "addresses.parquet", index=False)
    return len(df)


# ---- OS Code-Point Open ----------------------------------------------------------------
CODEPOINT_COLUMNS = ["postcode", "quality", "e", "n", "country", "nhs_region", "nhs_ha",
                     "county", "district", "ward"]


def _is_codepoint_data(name: str) -> bool:
    """Data CSVs, not the header and code lists in the Doc folder."""
    lower = name.lower().replace("\\", "/")
    return lower.endswith(".csv") and not re.search(r"(^|/)doc/", lower)


def _codepoint_frames(path: Path):
    path = Path(path)
    if path.is_dir():
        for csv in sorted(p for p in path.rglob("*.csv") if _is_codepoint_data(str(p))):
            yield pd.read_csv(csv, header=None, dtype={0: str}, usecols=[0, 2, 3])
        return
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if _is_codepoint_data(name):
                yield pd.read_csv(io.BytesIO(z.read(name)), header=None, dtype={0: str},
                                  usecols=[0, 2, 3])
            elif name.lower().endswith(".zip"):
                yield from _codepoint_frames_from_bytes(z.read(name))


def _codepoint_frames_from_bytes(blob: bytes):
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for name in z.namelist():
            if _is_codepoint_data(name):
                yield pd.read_csv(io.BytesIO(z.read(name)), header=None, dtype={0: str},
                                  usecols=[0, 2, 3])


def prepare_postcodes(path: Path, out: Path = OUT, cfg: dict | None = None) -> int:
    cfg = cfg or load_config()
    e0, n0, e1, n1 = _bbox(cfg)
    frames = [f.set_axis(["postcode", "e", "n"], axis=1) for f in _codepoint_frames(path)]
    if not frames:
        raise ValueError(f"No Code-Point Open CSV files found in {path}")
    df = pd.concat(frames, ignore_index=True)
    df["postcode"] = df["postcode"].str.replace(r"\s+", "", regex=True).str.upper()
    df = df[(df["e"] > 0) & df["e"].between(e0, e1) & df["n"].between(n0, n1)]
    out.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out / "postcodes.parquet", index=False)
    return len(df)


# ---- Existing and planned generation (from the pipeline) ------------------------------

def prepare_generation(db: Path, out: Path = OUT, cfg: dict | None = None) -> int:
    import duckdb

    from gbeg import export, pipeline

    cfg = cfg or load_config()
    e0, n0, e1, n1 = _bbox(cfg)
    with duckdb.connect(str(db)) as con:
        pipeline.build(con)
        df = con.execute("""
            WITH ecr AS (
                SELECT site_name AS name, technology, capacity_mw AS mw,
                       lifecycle_stage AS stage, 'ENWL register' AS source,
                       easting AS e, northing AS n, source_record_id AS id
                FROM int_site_records WHERE source LIKE 'ecr_%'
            ),
            matched AS (SELECT repd_id FROM int_site_matches
                        WHERE match_rule IN ('matched_name', 'matched_location'))
            SELECT * FROM ecr
            UNION ALL
            SELECT site_name, technology, capacity_mw, lifecycle_stage, 'REPD',
                   easting, northing, source_record_id
            FROM int_site_records
            WHERE source = 'repd'
              AND lifecycle_stage IN ('operational', 'under_construction', 'consented',
                                      'in_planning')
              AND coalesce(location_flag::VARCHAR, '') <> 'offshore'
              AND source_record_id NOT IN (SELECT repd_id FROM matched)
        """).df()
    df = df[df["e"].between(e0, e1) & df["n"].between(n0, n1)].copy()
    df["technology"] = df["technology"].map(export.TECHNOLOGY_LABELS).fillna("Other")
    df["status"] = df["stage"].map(export.STATUS_LABELS)
    ecr = df["source"].ne("REPD")
    df.loc[ecr, "status"] = df.loc[ecr, "stage"].map(export.ECR_STATUS_LABELS)
    df["name"] = df["name"].fillna("Unnamed").str.title()
    out.mkdir(parents=True, exist_ok=True)
    df[["name", "technology", "mw", "status", "source", "e", "n"]].to_csv(
        out / "generation.csv", index=False)
    return len(df)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("layer", choices=["ruc", "addresses", "postcodes", "generation"])
    parser.add_argument("path", nargs="?", type=Path)
    parser.add_argument("--db", type=Path, default=Path("data/processed/gbeg.duckdb"))
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    if args.layer == "generation":
        n = prepare_generation(args.db, args.out)
    else:
        if args.path is None:
            parser.error(f"{args.layer} needs the path to the downloaded file")
        n = {"ruc": prepare_ruc, "addresses": prepare_addresses,
             "postcodes": prepare_postcodes}[args.layer](args.path, args.out)
    print(f"{args.layer}: {n:,} records written to {args.out}")


if __name__ == "__main__":
    main()
