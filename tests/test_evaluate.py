import pandas as pd
import pytest

from gbeg import evaluate


@pytest.fixture
def labelled():
    # Two strata. matched_name stands for 100 pairs, weak_candidate for 40.
    return pd.DataFrame({
        "pair_id": range(1, 9),
        "stratum": ["matched_name"] * 4 + ["weak_candidate"] * 4,
        "stratum_size": [100] * 4 + [40] * 4,
        "distance_m": [50, 1500, 1800, 300, 1200, 1500, 1900, 1100],
        "name_similarity": [1.0, 0.9, 0.7, 0.8, 0.3, 0.4, None, 0.2],
        "capacity_ratio": [1.0, 1.1, 1.0, 1.2, 1.0, 1.5, 1.0, 1.0],
        "family_match": [True] * 8,
        "label": ["same", "same", "different", "same", "same", "different", "different",
                  "unsure"],
    })


def test_current_rule_accepts_only_named(labelled):
    accepted = evaluate.apply_rule(labelled, close_m=1000, name_match=0.6)
    assert accepted.tolist() == [True] * 4 + [False] * 4


def test_weighted_precision_and_recall(labelled):
    accepted = evaluate.apply_rule(labelled, close_m=1000, name_match=0.6)
    precision, recall = evaluate.precision_recall(labelled, accepted)
    # matched_name: 3 same, 1 different, each worth 25 -> tp 75, fp 25
    # weak_candidate: 3 decided, each worth 40/3; one same was rejected -> fn 13.33
    assert precision == pytest.approx(0.75)
    assert recall == pytest.approx(75 / (75 + 40 / 3), abs=1e-3)


def test_by_stratum_counts(labelled):
    table = evaluate.by_stratum(labelled)
    assert table.loc["matched_name", "same"] == 3
    assert table.loc["weak_candidate", "unsure"] == 1
    assert table.loc["weak_candidate", "share_same"] == pytest.approx(0.33)


def test_sweep_has_every_combination(labelled):
    result = evaluate.sweep(labelled, closes=(0, 1000), names=(0.6, 0.9))
    assert len(result) == 4


def test_rejects_unknown_label(tmp_path, labelled):
    path = tmp_path / "labels.xlsx"
    bad = labelled.assign(label=["maybe"] + labelled["label"].tolist()[1:])
    bad.rename(columns={"label": "Label", "distance_m": "Distance (m)"}).to_excel(
        path, sheet_name="Pairs", index=False
    )
    with pytest.raises(ValueError, match="maybe"):
        evaluate.load_labels(path)
