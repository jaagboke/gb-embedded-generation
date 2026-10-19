# Decision log

A running record of design decisions, data surprises and trade-offs. This is the raw
material for the Medium write-up, so record the *why* and any numbers at the time.

Format: date — decision — reason — alternatives considered.

---

**2026-10-13 — Scope: harmonised national register first, screening second.**
Reason: the pipeline is the data engineering showcase and stands alone if Phase 2 slips.
Alternatives: screening tool only (more analysis than engineering); ECR harmoniser only
(less distinctive).

**2026-10-13 — Start with two DNOs, not six.**
Reason: prove the pipeline end to end before absorbing every source's edge cases.

**2026-10-13 — DuckDB with the spatial extension as the store.**
Reason: zero infrastructure, runs in CI, handles spatial joins at this scale.
Alternatives: PostGIS (heavier to host for a portfolio project; revisit if it outgrows DuckDB).

**2026-10-13 — Store OSGB36 easting/northing as the canonical location, derive WGS84.**
Reason: most GB energy sources publish OS grid references or eastings/northings, and
distance calculations in metres are simpler in EPSG:27700.

**2026-10-13 — Normalise all capacities to MW and flag assumptions.**
Reason: sources mix kW, MW and apparent power (kVA/MVA). Converting silently would hide a
real data quality issue, so a flag column records any assumption made.

**2026-10-13 — REPD: take location from coordinates, never from the Country/Region label.**
Reason: some rows carry the wrong label (e.g. Highland sites tagged England) while their
coordinates are right.

**2026-10-13 — REPD: fix swapped coordinates automatically, but flag every fix.**
Rule: a Scotland-region row whose northing is below 530 km and easting above it is swapped;
any row outside the grid that becomes valid when swapped is swapped. Each fix sets
`location_flag = coords_swapped` so it stays auditable.

**2026-10-13 — Fail the load on any unmapped technology or status label.**
Reason: silently bucketing new labels into "other" hides source changes. The mapping lives
in `config/technology_map.yaml` and the loader raises with the unmapped values listed.

**2026-10-13 — Use a lifecycle stage, not only a connection status.**
REPD tracks planning status and ECRs track connection status. Both map onto one
`lifecycle_stage` enum so the sources can be compared.

**2026-10-13 — ECR technology: ordered regex rules on "source :: technology", not a lookup.**
Reason: ENWL's labels are free text with typos ("IRRESPECTVE", "STOAGE"), double spaces
and contradictions. An exact-match lookup would need an entry per spelling. Ordered rules
handle variants and stay reviewable; the load still fails if nothing matches. The rules
use the ENA vocabulary so they should carry to other DNOs (to be tested).

**2026-10-13 — ECR record ID: deterministic hash of identifying fields.**
Reason: ENWL's "Reference" is blank on 566 of 568 rows and MPANs are mostly withheld.
The hash uses site, postcode, coordinates, technology and status, plus an occurrence
number for exact repeats, so IDs are stable between runs of the same release.

**2026-10-13 — ECR capacity: registered capacity by connection status; export kept apart.**
Connected sites use "Already connected Registered Capacity", accepted sites use
"Accepted to Connect Registered Capacity", falling back to technology-1 registered
capacity. Registered capacity is closest to REPD's installed capacity, so it is the
matching field. `capacity_basis` records which column was used.

**2026-10-13 — Keep 99.9 MW values but flag them.**
Suspected placeholder. Matching showed 3 of the 9 flagged batteries have 99.9 MW in REPD
too, so at least some are genuine just-under-100 MW designs. Flag stays until each is
checked.

**2026-10-13 — First-pass matching: same technology family, within 1 km, capacity within 2x.**
Fossil generation is excluded from match rates because REPD does not cover it.

**2026-10-13 — Stage 3: add site-name similarity and widen candidates to 2 km.**
A pair is accepted when technologies agree, capacities are within 2x, and either the
sites are within 1 km (`matched_location`) or the names score at least 0.6
(`matched_name`). Pairs 1-2 km apart with dissimilar names are `weak_candidate`.
Reason: spot checks showed wind and solar farms with identical names 1-2 km apart
(ECR coordinates look like connection points, REPD coordinates like site centres), while
some sub-1 km pairs were clearly different sites.

**2026-10-13 — Name similarity: two comparisons, keep the higher.**
(1) token-set ratio after removing generic words (solar, farm, BESS, road, Ltd...);
(2) partial ratio with spaces squeezed out, used only as a containment test (score at
least 90, shorter name at least 6 characters). (2) catches "ELLEN ROAD" vs "Ellenroad" and
names made only of generic words ("PARK ROAD BESS"). Allowing middling partial scores
produced false positives ("Roanhead" vs "Lots Road" scored 0.67), hence the containment
cut-off.

**2026-10-13 — Measure matching on a stratified, hand-labelled sample.**
60 pairs: 15 matched_name, 20 matched_location, 10 weak_candidate, 10 capacity_mismatch,
5 nearby_other_technology, fixed seed. Rejected strata are sampled too, so recall can be
estimated, not just precision. Labeller sees both records and map links but not the rule
or similarity score, to avoid anchoring. Each label is weighted by stratum size to give
population estimates (`gbeg.evaluate`).

**2026-10-13 — Observation to test after labelling: operator names.**
Several `matched_location` pairs with unrelated site names share an operator and
capacity (e.g. ORRELL BESS / UKGEA vs Sandyforth Farm / UKGEA, both 70 MW). Operator
similarity is a candidate fourth piece of evidence, to be judged on the labels rather
than added on a hunch.

**2026-10-18 — Build the app before finishing validation.**
Reason: the project is a portfolio piece; something a reviewer can open in 30 seconds
matters more than a perfect precision figure nobody can see. The app labels its counts as
a first pass and explains that validation is in progress.

**2026-10-18 — App reads a single exported CSV, not the pipeline.**
`gbeg.export` writes `app/data/enwl_sites.csv`; the app needs only Streamlit, pandas and
pydeck. Deploys stay fast and the raw files never have to be published.

**2026-10-18 — Plain-English statuses in the app.**
Five match rules collapse to four statuses a non-specialist can read: In both registers,
Possible match, Not found in REPD, Fossil (not covered by REPD). Status conflicts are shown
as "worth checking", not as errors, because some come from location-only matches.

**2026-10-18 — The product is a site screening tool; the register pipeline feeds it.**
Reason: a data comparison viewer is interesting to data people but nobody uses it for a
task. Engineers placing temporary or standby generators need each site classed rural or
urban with evidence. The pipeline's reconciled register becomes the "generation nearby"
check.

**2026-10-18 — No company policy was available, so the rules are documented defaults.**
Urban if ONS urban or 50+ addresses within 250 m; rural if ONS rural, under 10 addresses
within 250 m and nearest at least 100 m; otherwise borderline. Noise: point source from the
generator's level at 7 m, against typical night backgrounds of 30/35/40 dB, banded at +5 and
+10 dB after BS 4142. All values are in `config/screening.yaml`, adjustable per run, and
written into every Excel report.

**2026-10-18 — Show the evidence, not only a verdict.**
There is no single definition of rural vs urban for generator siting, so every result
carries its inputs and the rule that fired. Borderline is a real outcome: those are the
sites that need a person to look.

**2026-10-18 — Read the user's file as it is.**
Columns are matched by loose name patterns with a manual override, and a single location
column may mix postcodes, grid references and coordinates. Rows that cannot be placed are
listed with the reason rather than dropped.

**2026-10-18 — Every reference layer is optional.**
The app runs with whatever reference data is present and says what it could not assess.
This keeps the public version honest while data is being added, and lets a company swap in
its own data via `GBEG_REFERENCE`.

---

## Results log

**2026-10-13 — ENWL ≥1MW ECR against REPD Q2 2026 (first pass, unvalidated).**
- 568 ENWL records: 179 fossil (1,941 MW) outside REPD scope; 389 REPD-eligible.
- Of the 389: 194 matched (50%, 3,870 MW), 33 capacity mismatch, 59 only other
  technologies nearby, 103 with no REPD record within 1 km (3,201 MW).
- Distance sensitivity: 37 matches within 100 m, 87 within 250 m, 136 within 500 m,
  194 within 1 km. Locations disagree more than expected, so name similarity is needed.
- 27 REPD sites are the target of more than one ECR record (phases or duplicates).
- Status disagreement on matched pairs: 64 of 194. For example, 11 sites are "accepted to
  connect" in the ECR but refused, withdrawn or expired in planning — candidates for
  stale connection queue entries.
- Spot checks show some 1 km matches are wrong (different site names), so precision must
  be measured on a labelled sample before these numbers are quoted.

---

**2026-10-13 — With name similarity (before labelling).**
Of 389 REPD-eligible ENWL records: 139 matched_name (2,310 MW), 64 matched_location
(1,667 MW), 18 weak_candidate, 54 capacity_mismatch, 74 nearby_other_technology,
40 with no REPD record within 2 km (1,568 MW).

---

## Data surprises (fill in as found)

| Date | Source | Issue | Rows affected | Handling |
|---|---|---|---|---|
| 2026-10-13 | REPD Q2 2026 | Latin-1 encoding, CRLF, newlines inside quoted fields (including coordinate fields) | 14,657 rows over 15,967 lines; 515 addresses span lines | Read as Latin-1, collapse whitespace in every field |
| 2026-10-13 | REPD Q2 2026 | Whitespace-only cells and trailing spaces in categories ("England ") | Country, Storage Type, Mounting Type, capacity | Strip and convert blanks to null |
| 2026-10-13 | REPD Q2 2026 | Easting and northing swapped on Scottish battery sites | 9 | Swapped back and flagged `coords_swapped` |
| 2026-10-13 | REPD Q2 2026 | Wrong Country label with correct coordinates (Highland and Lanarkshire sites tagged England) | 2 found | Ignore label, use coordinates |
| 2026-10-13 | REPD Q2 2026 | Offshore sites beyond the 700 km grid edge | 125 | Kept, flagged `offshore` (out of scope for a distribution register) |
| 2026-10-13 | REPD Q2 2026 | Missing coordinates | 36 | Flagged `coords_missing` |
| 2026-10-13 | REPD Q2 2026 | Missing installed capacity | 1,345 | Null |
| 2026-10-13 | REPD Q2 2026 | Re-applications create repeat records for one site (status "Revised") | 826 Revised; 890 rows share name and coordinates with another row | Kept with `superseded_by`; collapsed in deduplication step |
| 2026-10-13 | ENWL ECR ≥1MW | UTF-8 BOM, newlines inside column headers; comma-separated (not semicolon as expected for Opendatasoft) | All | utf-8-sig, collapse header whitespace |
| 2026-10-13 | ENWL ECR ≥1MW | No usable record ID: "Reference" blank, MPANs "DATA NOT AVAILABLE" | 566 / 568 blank references; 338 export MPANs withheld | Deterministic hash key |
| 2026-10-13 | ENWL ECR ≥1MW | Sentinel values for unknown: "DATA NOT AVAILABLE", "TO BE CONFIRMED", "-" | Across 14 columns | Converted to null |
| 2026-10-13 | ENWL ECR ≥1MW | Technology free text: typos, spacing variants, 25 source and 24 technology spellings | All | Ordered regex rules |
| 2026-10-13 | ENWL ECR ≥1MW | Contradictory labels, e.g. source "STORED ENERGY" with technology "ENGINE" or "CHP"; "SOLAR" with "STORAGE - ELECTROCHEMICAL" | Small number | Rule order decides; noted for review |
| 2026-10-13 | ENWL ECR ≥1MW | Inconsistent licence area values: ELECTRICITY NORTH WEST LIMITED / PLC, SPENWL, SPENW, and one NORTHERN POWERGRID | 568 | Kept raw; DNO set to ENWL |
| 2026-10-13 | ENWL ECR ≥1MW | 99.9 MW on accepted-to-connect batteries | 9 | Kept, flagged `capacity_99_9_check` |
| 2026-10-13 | ENWL ECR ≥1MW | Exact repeat records (same site, location, technology, status) | 2 pairs | Flagged `possible_duplicate` |
| 2026-10-13 | ENWL ECR ≥1MW | Coordinates clean: all inside the North West, geopoint agrees with eastings/northings | 0 issues | None needed |
