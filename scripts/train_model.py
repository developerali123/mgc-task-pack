"""
Train the intake-time lead scoring baseline and persist artifacts.

Usage:
    python scripts/train_model.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.lead_scoring import (  # noqa: E402
    CATEGORICAL_FEATURES,
    FEATURE_COLUMNS,
    NUMERIC_FEATURES,
    TARGET_COLUMN,
    clean_leads_frame,
    dedupe_leads,
    leads_to_feature_frame,
    score_lead,
    load_model,
)

CSV_PATH = ROOT / "leads.csv"
MODEL_PATH = ROOT / "models" / "lead_scoring_model.joblib"
METRICS_PATH = ROOT / "reports" / "model_metrics.json"
RANDOM_STATE = 42
TRAIN_FRACTION = 0.80


def chronological_split(df: pd.DataFrame, train_fraction: float = TRAIN_FRACTION):
    ordered = df.sort_values("created_at", kind="mergesort").reset_index(drop=True)
    if ordered["created_at"].isna().any():
        raise ValueError("created_at has nulls after parsing; cannot time-split")
    cut = int(len(ordered) * train_fraction)
    if cut <= 0 or cut >= len(ordered):
        raise ValueError("Train fraction leaves an empty train or test set")
    train = ordered.iloc[:cut].copy()
    test = ordered.iloc[cut:].copy()
    # Ensure no time leakage: max(train) <= min(test)
    assert train["created_at"].max() <= test["created_at"].min()
    return train, test, cut


def build_pipeline() -> Pipeline:
    categorical = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="most_frequent")),
            (
                "onehot",
                OneHotEncoder(handle_unknown="ignore", sparse_output=False),
            ),
        ]
    )
    numeric = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
        ]
    )
    preprocess = ColumnTransformer(
        transformers=[
            ("cat", categorical, CATEGORICAL_FEATURES),
            ("num", numeric, NUMERIC_FEATURES),
        ]
    )
    clf = LogisticRegression(
        max_iter=1000,
        class_weight="balanced",
        random_state=RANDOM_STATE,
        solver="lbfgs",
    )
    return Pipeline(steps=[("preprocess", preprocess), ("model", clf)])


def top_k_conversions(y_true: np.ndarray, y_score: np.ndarray, k: int = 100) -> dict:
    n = len(y_true)
    if n == 0:
        return {
            "k_requested": k,
            "k_used": 0,
            "conversions_in_top_k": 0,
            "top_k_conversion_rate": None,
            "note": "Empty test set",
        }
    k_used = min(k, n)
    order = np.argsort(-y_score, kind="mergesort")
    top = y_true[order[:k_used]]
    conversions = int(top.sum())
    return {
        "k_requested": k,
        "k_used": k_used,
        "conversions_in_top_k": conversions,
        "top_k_conversion_rate": float(conversions / k_used),
    }


def main() -> None:
    raw = pd.read_csv(CSV_PATH)
    cleaned = clean_leads_frame(raw)

    # Target validation
    if cleaned[TARGET_COLUMN].isna().any():
        raise ValueError("converted contains nulls")
    y_all = cleaned[TARGET_COLUMN].astype(int)
    if not set(y_all.unique()).issubset({0, 1}):
        raise ValueError("converted is not binary")

    before = len(cleaned)
    deduped = dedupe_leads(cleaned)
    n_dup_removed = before - len(deduped)

    train_df, test_df, cut_idx = chronological_split(deduped)

    X_train = leads_to_feature_frame(train_df)
    X_test = leads_to_feature_frame(test_df)
    y_train = train_df[TARGET_COLUMN].astype(int).to_numpy()
    y_test = test_df[TARGET_COLUMN].astype(int).to_numpy()

    split_boundary = {
        "train_end_created_at": train_df["created_at"].max().isoformat(sep=" "),
        "test_start_created_at": test_df["created_at"].min().isoformat(sep=" "),
        "train_row_cutoff_index": int(cut_idx),
        "train_fraction": TRAIN_FRACTION,
    }

    metrics: dict = {
        "model_type": "LogisticRegression",
        "random_state": RANDOM_STATE,
        "prediction_time": "intake",
        "feature_columns": FEATURE_COLUMNS,
        "categorical_features": CATEGORICAL_FEATURES,
        "numeric_features": NUMERIC_FEATURES,
        "dataset": {
            "csv_rows": int(before),
            "rows_after_dedupe": int(len(deduped)),
            "duplicate_rows_removed": int(n_dup_removed),
            "date_range_start": deduped["created_at"].min().isoformat(sep=" "),
            "date_range_end": deduped["created_at"].max().isoformat(sep=" "),
            "positive_rate_overall": float(deduped[TARGET_COLUMN].mean()),
            "train_rows": int(len(train_df)),
            "test_rows": int(len(test_df)),
            "train_positives": int(y_train.sum()),
            "test_positives": int(y_test.sum()),
            "train_positive_rate": float(y_train.mean()),
            "test_positive_rate": float(y_test.mean()) if len(y_test) else None,
        },
        "split": split_boundary,
        "class_imbalance_handling": "class_weight='balanced'",
    }

    # Guard: both classes needed for meaningful ranking metrics
    if len(np.unique(y_train)) < 2:
        raise RuntimeError("Training set has a single class; cannot fit classifier")
    if len(y_test) == 0:
        raise RuntimeError("Empty test set")
    if len(np.unique(y_test)) < 2:
        metrics["primary_metric"] = {
            "name": "average_precision",
            "value": None,
            "no_skill_baseline_test_prevalence": float(y_test.mean()),
            "limitation": (
                "Test set contains only one class; average precision is not "
                "meaningful to report as a comparative score."
            ),
        }
        pipe = build_pipeline()
        pipe.fit(X_train, y_train)
        scores = pipe.predict_proba(X_test)[:, 1]
        biz = top_k_conversions(y_test, scores, k=100)
        metrics["business_metric_top_100"] = {
            **biz,
            "test_set_conversion_rate": float(y_test.mean()),
            "test_leads": int(len(y_test)),
            "note": "Primary AP metric unavailable due to single-class test set.",
        }
    else:
        pipe = build_pipeline()
        pipe.fit(X_train, y_train)
        scores = pipe.predict_proba(X_test)[:, 1]

        ap = float(average_precision_score(y_test, scores))
        prevalence = float(y_test.mean())
        metrics["primary_metric"] = {
            "name": "average_precision",
            "display_name": "Average Precision (PR-AUC)",
            "value": ap,
            "no_skill_baseline": {
                "definition": (
                    "Positive-class prevalence in the chronological test set "
                    "(expected AP of an unskilled constant/random scorer)."
                ),
                "value": prevalence,
            },
            "interpretation": (
                "Higher is better. Values near the prevalence baseline indicate "
                "little ranking lift over calling leads at random."
            ),
        }

        biz = top_k_conversions(y_test, scores, k=100)
        metrics["business_metric_top_100"] = {
            "description": (
                "Among the top 100 test leads ranked by predicted P(convert), "
                "how many actually converted. Distinct from average precision."
            ),
            "test_leads": int(len(y_test)),
            "test_set_conversions": int(y_test.sum()),
            "test_set_conversion_rate": prevalence,
            **biz,
        }

        # Honest performance note
        lift = ap / prevalence if prevalence > 0 else None
        metrics["performance_note"] = (
            f"Test AP={ap:.4f} vs prevalence baseline={prevalence:.4f} "
            f"(ratio={lift:.2f}x). "
            + (
                "Modest ranking lift only; treat as a weak baseline prioritization aid."
                if lift is not None and lift < 2.0
                else "Some ranking lift over prevalence; still a simple baseline."
                if lift is not None
                else "Baseline comparison unavailable."
            )
        )

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipe, MODEL_PATH)
    METRICS_PATH.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    # Smoke-test inference with a realistic intake lead
    load_model(MODEL_PATH)  # reset cache path
    sample = {
        "source": "Referral",
        "city": "Islamabad",
        "area": "GT Road Corridor",
        "property_type": "Apartment",
        "budget_pkr_lac": 120.0,
        "bedrooms": 2,
        "is_overseas": 0,
        "referred_by_existing_client": 1,
        "has_financing_approved": 0,
    }
    scored = score_lead(sample)
    assert 0.0 <= scored["conversion_probability"] <= 1.0

    print("=== Training complete ===")
    print(json.dumps(metrics["primary_metric"], indent=2))
    print(json.dumps(metrics["business_metric_top_100"], indent=2))
    print("Saved model:", MODEL_PATH)
    print("Saved metrics:", METRICS_PATH)
    print("Sample score_lead:", scored)


if __name__ == "__main__":
    main()
