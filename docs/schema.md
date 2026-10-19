# Target schema

## `mart_sites` — one row per distinct generation/storage site

| Column | Type | Notes |
|---|---|---|
| `site_id` | text | Stable internal ID, hash of source + source record ID of the primary record |
| `site_name` | text | Cleaned name |
| `dno` | text | e.g. `SPEN`, `NGED`, `UKPN`, `NPg`, `ENWL`, `SSEN` |
| `licence_area` | text | e.g. `SPM`, `SPD`, `SEPD` |
| `technology` | text | Harmonised enum, see below |
| `technology_raw` | text | As published |
| `export_capacity_mw` | double | Normalised to MW |
| `capacity_unit_flag` | text | Set when a conversion assumption was made (e.g. kVA treated as kW) |
| `lifecycle_stage` | text | `operational`, `under_construction`, `consented`, `in_planning`, `inactive`, `decommissioned`, `superseded`, `other`. ECR "accepted to connect" maps to `consented` |
| `connection_status_raw` | text | ECR connection status as published |
| `connection_voltage_kv` | double | Nullable |
| `easting` | integer | OSGB36 / EPSG:27700 |
| `northing` | integer | OSGB36 / EPSG:27700 |
| `latitude` | double | WGS84 |
| `longitude` | double | WGS84 |
| `location_quality` | text | `grid_ref`, `coordinates`, `postcode_centroid`, `missing` |
| `location_flag` | text | `coords_swapped`, `offshore`, `coords_missing`, `coords_invalid`, or null |
| `sources` | text[] | Every source that contributed a record |
| `source_release` | text | Release identifier of the primary record |
| `first_seen` | date | First release containing the site |
| `last_seen` | date | Latest release containing the site |

## Harmonised technology enum

Defined in `config/technology_map.yaml`, alongside the raw-to-enum mapping for each source,
so the mapping itself is reviewable and versioned.

## Supporting tables

- `int_site_records` — one row per source record after staging, before deduplication.
- `int_site_matches` — candidate matches between records with match score and rule fired.
- `mart_site_screening` (Phase 2) — `site_id`, `ruc_2021_class`, `background_noise_db`,
  `nearest_dwelling_m`, `screening_class`, `rule_trace`.
