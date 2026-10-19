"""Build the intermediate tables from the staged sources.

int_site_records      one row per source record, common columns only
int_match_candidates  every ECR-REPD pair within CANDIDATE_RADIUS_M, with its evidence
int_site_matches      best REPD candidate for each ECR record, with the rule that fired

Matching is transparent rather than clever. Each candidate pair carries four pieces of
evidence: distance, capacity ratio, technology-family agreement and site-name
similarity. A pair is accepted when the technologies agree, the capacities are compatible,
and either the sites are close or the names agree. The thresholds are constants so they
can be tuned against the hand-labelled sample (see gbeg.evaluate) and the effect reported.
"""

from __future__ import annotations

import argparse
import contextlib
from pathlib import Path

import duckdb

from gbeg.transform.names import similarity

try:  # DuckDB >= 1.4
    from duckdb.sqltypes import DOUBLE, VARCHAR
except ImportError:  # older DuckDB
    from duckdb.typing import DOUBLE, VARCHAR

CANDIDATE_RADIUS_M = 2_000   # pairs further apart than this are never considered
CLOSE_M = 1_000              # close enough to accept on location alone
NAME_MATCH = 0.6             # name similarity that accepts a pair up to CANDIDATE_RADIUS_M
CAPACITY_RATIO = 2.0

# Technologies that REPD covers. Fossil generation is outside REPD's scope, so ECR records
# for it can never match and are reported separately rather than counted as misses.
FAMILY_SQL = """
CASE
    WHEN technology IN ('battery_storage', 'other_storage', 'pumped_storage') THEN 'storage'
    WHEN technology IN ('fossil_gas', 'fossil_oil') THEN 'fossil'
    ELSE technology
END
"""

COMMON = """
    source, source_record_id, site_name, operator, technology, technology_raw,
    capacity_mw, lifecycle_stage, lifecycle_raw, postcode,
    easting, northing, latitude, longitude, location_quality, location_flag
"""


def build(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(f"""
        CREATE OR REPLACE TABLE int_site_records AS
        SELECT {COMMON}, NULL::VARCHAR AS dno, {FAMILY_SQL} AS technology_family
        FROM stg_repd
        UNION ALL BY NAME
        SELECT {COMMON}, dno, {FAMILY_SQL} AS technology_family
        FROM stg_ecr_enwl
    """)

    _register_udfs(con)
    con.execute(f"""
        CREATE OR REPLACE TABLE int_match_candidates AS
        WITH ecr AS (
            SELECT * FROM int_site_records
            WHERE source LIKE 'ecr_%' AND easting IS NOT NULL
        ),
        repd AS (
            SELECT * FROM int_site_records
            WHERE source = 'repd' AND easting IS NOT NULL
              AND lifecycle_stage <> 'superseded'
              AND coalesce(location_flag::VARCHAR, '') <> 'offshore'
        )
        SELECT
            e.source_record_id AS ecr_id,
            r.source_record_id AS repd_id,
            round(sqrt(power(e.easting - r.easting, 2) + power(e.northing - r.northing, 2)))
                AS distance_m,
            round(greatest(e.capacity_mw, r.capacity_mw)
                / nullif(least(e.capacity_mw, r.capacity_mw), 0), 2) AS capacity_ratio,
            e.technology_family = r.technology_family
                OR (e.technology = 'hybrid'
                    AND r.technology_family IN ('solar_pv', 'storage', 'onshore_wind'))
                AS family_match,
            name_similarity(e.site_name, r.site_name) AS name_similarity
        FROM ecr e
        JOIN repd r
          ON abs(e.easting - r.easting) <= {CANDIDATE_RADIUS_M}
         AND abs(e.northing - r.northing) <= {CANDIDATE_RADIUS_M}
        WHERE sqrt(power(e.easting - r.easting, 2) + power(e.northing - r.northing, 2))
              <= {CANDIDATE_RADIUS_M}
    """)

    con.execute(f"""
        CREATE OR REPLACE TABLE int_site_matches AS
        WITH scored AS (
            SELECT *,
                coalesce(capacity_ratio <= {CAPACITY_RATIO}, TRUE) AS capacity_ok,
                coalesce(name_similarity >= {NAME_MATCH}, FALSE) AS name_ok,
                distance_m <= {CLOSE_M} AS close
            FROM int_match_candidates
        ),
        ranked AS (
            SELECT *,
                row_number() OVER (
                    PARTITION BY ecr_id
                    ORDER BY family_match DESC, name_ok DESC, capacity_ok DESC,
                             coalesce(name_similarity, 0) DESC, distance_m
                ) AS rnk
            FROM scored
        )
        SELECT
            ecr_id, repd_id, distance_m, capacity_ratio, family_match, name_similarity,
            CASE
                WHEN NOT family_match THEN 'nearby_other_technology'
                WHEN NOT capacity_ok THEN 'capacity_mismatch'
                WHEN name_ok THEN 'matched_name'
                WHEN close THEN 'matched_location'
                ELSE 'weak_candidate'
            END AS match_rule
        FROM ranked
        WHERE rnk = 1
    """)


def _register_udfs(con: duckdb.DuckDBPyConnection) -> None:
    with contextlib.suppress(Exception):  # not registered yet on this connection
        con.remove_function("name_similarity")
    con.create_function(
        "name_similarity", similarity, [VARCHAR, VARCHAR], DOUBLE,
        null_handling="special",  # similarity() returns None when a name has no identity
    )


def summary(con: duckdb.DuckDBPyConnection) -> list[tuple]:
    return con.execute("""
        SELECT
            CASE WHEN r.technology_family = 'fossil' THEN 'fossil (outside REPD scope)'
                 ELSE 'REPD-eligible' END AS scope,
            CASE WHEN r.technology_family = 'fossil' THEN 'not_applicable'
                 ELSE coalesce(m.match_rule, 'no_repd_record_within_2km') END AS outcome,
            count(*) AS ecr_records,
            round(sum(r.capacity_mw), 1) AS capacity_mw
        FROM int_site_records r
        LEFT JOIN int_site_matches m ON m.ecr_id = r.source_record_id
        WHERE r.source LIKE 'ecr_%'
        GROUP BY ALL
        ORDER BY scope DESC, ecr_records DESC
    """).fetchall()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build intermediate tables in DuckDB")
    parser.add_argument("--db", type=Path, default=Path("data/processed/gbeg.duckdb"))
    args = parser.parse_args()
    with duckdb.connect(str(args.db)) as con:
        build(con)
        print(f"{'scope':30} {'outcome':32} {'records':>8} {'MW':>9}")
        for scope, outcome, n, mw in summary(con):
            print(f"{scope:30} {outcome:32} {n:>8} {mw or 0:>9}")


if __name__ == "__main__":
    main()
