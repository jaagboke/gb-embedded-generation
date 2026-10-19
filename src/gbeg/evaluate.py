"""Measure matching quality against the hand-labelled sample.

Reads labels/match_sample.xlsx (written by gbeg.labelling, labelled by hand) and reports:

1. Per stratum: how many sampled pairs were labelled same / different / unsure.
2. Precision of the accepted matches, weighted back to the full population using the
   stratum sizes, and an estimate of how many true matches the rules reject.
3. A threshold sweep: precision and recall on the labelled pairs for alternative values of
   the "close" distance and the name-similarity threshold, so the trade-off is visible.

Each labelled pair stands for stratum_size / labelled_in_stratum pairs in the population.
"Unsure" labels are excluded from every rate and counted separately.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from gbeg import pipeline

ACCEPTED = {"matched_name", "matched_location"}


def load_labels(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name="Pairs")
    df = df.rename(columns={"Pair": "pair_id", "Label": "label", "Distance (m)": "distance_m"})
    df["label"] = df["label"].astype("string").str.strip().str.lower()
    bad = set(df["label"].dropna()) - {"same", "different", "unsure"}
    if bad:
        raise ValueError(f"Unexpected labels: {sorted(bad)}")
    return df


def _weights(df: pd.DataFrame) -> pd.Series:
    decided = df[df["label"].isin(["same", "different"])]
    per_stratum = decided.groupby("stratum")["label"].transform("size")
    return decided["stratum_size"] / per_stratum


def by_stratum(df: pd.DataFrame) -> pd.DataFrame:
    table = (
        df.assign(label=df["label"].fillna("unlabelled"))
        .pivot_table(index="stratum", columns="label", values="pair_id", aggfunc="count",
                     fill_value=0)
    )
    for col in ("same", "different", "unsure", "unlabelled"):
        if col not in table:
            table[col] = 0
    table["share_same"] = (table["same"] / (table["same"] + table["different"])).round(2)
    sizes = df.groupby("stratum")["stratum_size"].first()
    table["population"] = sizes
    table["est_same_in_population"] = (table["share_same"] * sizes).round(0)
    return table[["population", "same", "different", "unsure", "unlabelled", "share_same",
                  "est_same_in_population"]]


def apply_rule(df: pd.DataFrame, close_m: float, name_match: float,
               capacity_ratio: float = pipeline.CAPACITY_RATIO) -> pd.Series:
    """Re-apply the acceptance rule to the labelled pairs with alternative thresholds."""
    capacity_ok = df["capacity_ratio"].isna() | (df["capacity_ratio"] <= capacity_ratio)
    name_ok = df["name_similarity"].fillna(0) >= name_match
    close = df["distance_m"] <= close_m
    return df["family_match"].astype(bool) & capacity_ok & (name_ok | close)


def precision_recall(df: pd.DataFrame, accepted: pd.Series) -> tuple[float, float]:
    decided = df["label"].isin(["same", "different"])
    w = _weights(df)
    same = df["label"].eq("same") & decided
    tp = w[(accepted & same)[decided].values].sum() if decided.any() else 0
    fp = w[(accepted & ~same)[decided].values].sum() if decided.any() else 0
    fn = w[(~accepted & same)[decided].values].sum() if decided.any() else 0
    precision = tp / (tp + fp) if tp + fp else float("nan")
    recall = tp / (tp + fn) if tp + fn else float("nan")
    return round(precision, 3), round(recall, 3)


def sweep(df: pd.DataFrame, closes=(0, 100, 250, 500, 1000),
          names=(0.5, 0.6, 0.7, 0.8, 0.9)) -> pd.DataFrame:
    rows = []
    for close_m in closes:
        for name_match in names:
            p, r = precision_recall(df, apply_rule(df, close_m, name_match))
            rows.append({"close_m": close_m, "name_match": name_match,
                         "precision": p, "recall": r})
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate matching against labels")
    parser.add_argument("labels", type=Path, nargs="?",
                        default=Path("labels/match_sample.xlsx"))
    args = parser.parse_args()
    df = load_labels(args.labels)
    decided = df["label"].isin(["same", "different"]).sum()
    print(f"Labelled pairs: {df['label'].notna().sum()} of {len(df)} "
          f"({decided} same/different, {df['label'].eq('unsure').sum()} unsure)\n")
    if not decided:
        raise SystemExit("No same/different labels yet; fill in the Label column first.")

    print("By stratum (rule the matcher gave the pair):")
    print(by_stratum(df).to_string(), "\n")

    current = apply_rule(df, pipeline.CLOSE_M, pipeline.NAME_MATCH)
    p, r = precision_recall(df, current)
    print(f"Current rule (close <= {pipeline.CLOSE_M} m or name >= {pipeline.NAME_MATCH}): "
          f"precision {p}, recall {r}  (weighted to population)\n")

    print("Threshold sweep:")
    table = sweep(df).pivot(index="close_m", columns="name_match",
                            values=["precision", "recall"])
    print(table.to_string())


if __name__ == "__main__":
    main()
