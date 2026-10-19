import pytest

from gbeg.transform.names import normalise, similarity


def test_normalise_drops_generic_words():
    assert normalise("Clifton Marsh Farm, Preston New Road - Solar Farm") == (
        "clifton marsh preston new"
    )
    assert normalise("NORTH FARM BESS PLANT NO 2") == ""


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("CLIFTON MARSH", "Clifton Marsh Farm, Preston New Road - Solar Farm"),
        ("OLDSIDE WIND FARM", "Oldside Wind Farm"),
        ("HUNTROYDE", "Huntroyde Battery Storage"),
        ("PARK ROAD BESS", "Park Road Battery Storage"),
        ("ELLEN ROAD BESS", "Ellenroad Farm, Bentgate Street - Battery Energy Storage System"),
        ("MOOR HOUSE SOLAR PARK", "Moorhouse Farm"),
    ],
)
def test_same_site_scores_high(a, b):
    assert similarity(a, b) >= 0.9


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("ROANHEAD SOLAR FARM", "Bleabeck Solar Farm, Lots Road - Solar Farm"),
        ("HELLRIGG WIND FARM", "Park Head Farm"),
    ],
)
def test_different_sites_score_low(a, b):
    assert similarity(a, b) < 0.6


def test_no_identifying_words_returns_none():
    assert similarity("SOLAR BESS", "Clifton Marsh") is None
    assert similarity(None, "Clifton Marsh") is None
