# Generator site screening: method and assumptions

## Who it is for

An engineer or planner at a network operator who needs to place **temporary or standby
generators** (for outages, maintenance or resilience) and has to know, for each candidate
site, whether it counts as rural or urban, how close the neighbours are, and whether the
generator is likely to cause a noise problem.

They upload their own list of sites. The tool returns a screening table, a map and a
spreadsheet they can attach to their own assessment.

## What it is not

A screening tool, not a noise assessment. It does not replace a BS 4142 assessment, a site
visit, or the operator's own policy. Every default below is an assumption, labelled as
one, and can be changed.

## Input file

CSV or Excel, one row per site. Column names are matched loosely, so most layouts work.

| Column | Required | Accepted forms |
|---|---|---|
| Site name or ID | Yes | any text |
| Location | Yes | postcode, OS grid reference (e.g. `SJ 838 980`), easting + northing, or latitude + longitude, in one column or two |
| Generator rating (kVA) | No | number |
| Noise at 7 m, dB(A) | No | number, from the generator data sheet |
| Operating period | No | `day`, `night` or `24h` (default `24h`, assessed at night) |

## Checks per site

1. **Location.** Converted to OSGB36 and WGS84. Rows that cannot be placed, or fall outside
   the area covered, are listed with the reason.
2. **ONS 2021 Rural Urban Classification** of the output area the site falls in.
3. **Addresses nearby** from OS Open UPRN: distance to the nearest address and the count
   within 250 m and 500 m. OS Open UPRN includes every addressable object, not only homes,
   so these are addresses, not dwellings.
4. **Setting** (rural / borderline / urban):
   - *Urban* if ONS says urban, or there are at least 50 addresses within 250 m.
   - *Rural* if ONS says rural, there are fewer than 10 addresses within 250 m, and the
     nearest is at least 100 m away.
   - *Borderline* otherwise. These are the sites worth a closer look.
5. **Indicative noise at the nearest address.** Predicted level
   `L = L7 − 20·log10(d / 7)`, where `L7` is the generator's level at 7 m and `d` the
   distance to the nearest address. This treats the generator as a point source with no
   screening, which overstates the level in most real sites, so it errs on the cautious
   side. If no level is given, one is assumed from the kVA rating.
6. **Comparison with background.** The predicted level is compared with an assumed typical
   background for the setting (night LA90: rural 30 dB, borderline 35 dB, urban 40 dB;
   day 5 dB higher). The bands follow the BS 4142 convention that an excess of around
   +10 dB indicates a likely significant adverse impact and around +5 dB an adverse impact.
   No acoustic feature corrections are applied.
7. **Generation already nearby** within 2 km, from the DNO Embedded Capacity Register and
   REPD.

Each result carries a plain-English reason, so a reviewer can see why a site was classed
the way it was.

## Known limits

- Background levels are typical values, not measurements. Replace with survey data where
  it exists.
- Distance is to the nearest address point, which sits near the middle of a building, not
  its facade or garden boundary.
- ONS classifies whole output areas; a site at the edge of a town can sit in a rural area
  and vice versa. The address count is there to catch those cases.
- Coverage is North West England, Cheshire, Merseyside and North Wales in this version.
