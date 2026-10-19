# Roadmap

**End product:** a generator site screening tool. A user uploads their own site list and
gets setting, neighbours, indicative noise and nearby generation for each site, with
reasons and a downloadable report. The generation pipeline (stages 1-6) feeds it.

Tick items off as they land. Each stage ends with something that works and can be shown.

## Stage 1 — Foundations ✅
- [x] Repo structure, CI, schema, decision log
- [x] Coordinate and capacity normalisation with tests

## Stage 2 — Ingest two sources ✅
- [x] REPD staged with data quality fixes
- [x] ENWL ECR (≥1MW) staged with rule-based technology classification
- [x] First ECR-to-REPD match and summary table

## Stage 3 — Make the matching trustworthy (in progress)
- [x] Add site-name similarity to the match score (tokenised, ignoring "solar farm", "BESS" etc.)
- [x] Stratified sample of 60 pairs and evaluation script (`gbeg.labelling`, `gbeg.evaluate`)
- [ ] Hand-label the sample (`labels/match_sample.xlsx`)
- [ ] Tune radius and capacity ratio against the labelled sample; record the trade-off
- [ ] Resolve many-to-one matches (several ECR rows pointing at one REPD site)
- [ ] Collapse REPD re-application chains using `superseded_by`

## Stage 4 — Build the mart
- [ ] `mart_sites`: one row per site, merged attributes, `sources` lineage
- [ ] Data quality tests on the mart (unique `site_id`, valid enums, locations in GB)
- [ ] Move SQL into dbt models (`stg_` / `int_` / `mart_`) with dbt tests

## Stage 5 — Automate
- [ ] Single command `make pipeline` that runs everything end to end
- [ ] Scheduled GitHub Action that refreshes when a new release appears
- [ ] Release-over-release change log (sites added, removed, status changed)

## Stage 6 — Add sources
- [ ] ENWL ECR under 1MW
- [ ] SPEN (Manweb) ECR
- [ ] One or more further DNOs to prove the ECR rules generalise

## Stage 7 — Site screening (the product) — in progress
- [x] Upload any CSV/Excel layout; column detection with manual override
- [x] Locations from postcode, grid reference, easting/northing or lat/long, per row
- [x] Configurable rules (`config/screening.yaml`) with a reason for every result
- [x] Indicative noise check (point source, BS 4142-style bands) with kVA fallback
- [x] Generation within 2 km from the ENWL register and REPD
- [x] Excel report: results, rows not screened, assumptions
- [x] Prep scripts for ONS RUC, OS Open UPRN, Code-Point Open (tested on synthetic files)
- [ ] Load the real ONS, UPRN and Code-Point files
- [ ] Defra Round 4 (England) and Welsh Government noise maps to replace assumed background
- [ ] SPEN Manweb register and primary substation capacity for network context

## Stage 8 — Present (started early, 2026-10-18)
- [x] Streamlit app v1: map coloured by match status, filters, site comparison, data-quality and method tabs
- [ ] Deploy to Streamlit Community Cloud; add link to README and CV
- [x] Screening page with map, table and per-site explanation
- [ ] README with architecture diagram, results and how to run
- [ ] Medium article drafted from `docs/decision-log.md`
