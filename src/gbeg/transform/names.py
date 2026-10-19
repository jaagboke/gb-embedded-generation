"""Site-name normalisation and similarity.

Site names in REPD and the ECRs describe the same place differently:
"CLIFTON MARSH" vs "Clifton Marsh Farm, Preston New Road - Solar Farm". Generic words
("solar", "farm", "BESS", "Ltd") carry no identity, so they are removed before comparing.
Two comparisons are made and the higher score kept:
- token-set ratio on names with generic words removed ("clifton marsh" vs "clifton marsh
  preston new"), which ignores word order and extra words;
- partial ratio on names with only technology and company words removed and spaces
  squeezed out, which catches joined spellings ("ellen road" vs "ellenroad") and names
  made only of words like "park road". It only counts as near-containment (score of at
  least PARTIAL_CONTAINS) and is skipped when the shorter name is under MIN_PARTIAL_CHARS
  characters, because short strings match inside almost anything.
"""

from __future__ import annotations

import re

from rapidfuzz import fuzz

STOPWORDS = frozenset(
    """
    a an and at by for in of on the to system
    ltd limited plc llp co company group holdings uk
    solar pv photovoltaic farm farms park parks wind turbine turbines windfarm
    battery batteries bess storage energy power electricity generation generating
    station plant facility facilities project scheme site sites development
    extension phase phases no ii iii iv
    gas landfill biogas biomass hydro anaerobic digestion ad chp engine engines
    road lane street land at near adjacent east west north south
    """.split()
)

# Words that never identify a site, even when nothing else is left.
TECH_AND_COMPANY = frozenset(
    """
    a an and of the
    ltd limited plc llp co company group holdings uk
    solar pv photovoltaic wind turbine turbines battery batteries bess storage energy
    power electricity generation generating station plant facility project scheme system
    farm farms
    """.split()
)
MIN_PARTIAL_CHARS = 6
PARTIAL_CONTAINS = 90

_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")


def normalise(name: str | None) -> str:
    """Lower-case, strip punctuation and generic words; return space-joined tokens."""
    if not name:
        return ""
    text = _NON_ALNUM.sub(" ", name.lower())
    tokens = [t for t in text.split() if t not in STOPWORDS and not t.isdigit()]
    return " ".join(tokens)


def _light(name: str | None) -> str:
    if not name:
        return ""
    text = _NON_ALNUM.sub(" ", name.lower())
    return "".join(t for t in text.split() if t not in TECH_AND_COMPANY and not t.isdigit())


def similarity(a: str | None, b: str | None) -> float | None:
    """0-1 similarity of two site names, or None if either has no identifying words."""
    scores = []
    na, nb = normalise(a), normalise(b)
    if na and nb:
        scores.append(fuzz.token_set_ratio(na, nb))
    shorter, longer = sorted((_light(a), _light(b)), key=len)
    if len(shorter) >= MIN_PARTIAL_CHARS:
        # Used only as a containment test; middling partial scores are mostly noise.
        partial = fuzz.partial_ratio(shorter, longer)
        if partial >= PARTIAL_CONTAINS:
            scores.append(partial)
    return round(max(scores) / 100, 3) if scores else None
