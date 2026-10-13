"""
Intake-time lead conversion scoring for MGC.

Prediction time: at/near lead intake — before outbound calling, WhatsApp
follow-up, site visits, or token payment. Features are limited to fields that
are plausibly known when the lead is first captured in the CRM.

This module loads the persisted sklearn Pipeline and exposes score_lead().
Training lives in scripts/train_model.py.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL_PATH = ROOT / "models" / "lead_scoring_model.joblib"

# ---------------------------------------------------------------------------
# Feature contract (must match training)
# ---------------------------------------------------------------------------

CATEGORICAL_FEATURES = [
    "source",
    "city",
    "area",
    "property_type",
]

NUMERIC_FEATURES = [
    "budget_pkr_lac",
    "bedrooms",
    "is_overseas",
    "referred_by_existing_client",
    "has_financing_approved",
]

FEATURE_COLUMNS = CATEGORICAL_FEATURES + NUMERIC_FEATURES

TARGET_COLUMN = "converted"

# Excluded from the intake model — see README Part 3 for rationale
EXCLUDED_COLUMNS = [
    "lead_id",
    "created_at",
    "crm_record_hash",
    "converted",
    "calls_made",
    "total_call_seconds",
    "whatsapp_replies",
    "site_visits",
    "token_amount_received_pkr",
    "first_response_minutes",
    "agent_experience_years",
]

KNOWN_CITIES = {
    "ISB": "Islamabad",
    "ISLAMABAD": "Islamabad",
    "RWP": "Rawalpindi",
    "RAWALPINDI": "Rawalpindi",
    "KHI": "Karachi",
    "KARACHI": "Karachi",
    "LAHORE": "Lahore",
    "PESHAWAR": "Peshawar",
    "FAISALABAD": "Faisalabad",
    "MULTAN": "Multan",
    "GUJRANWALA": "Gujranwala",
    "ABBOTTABAD": "Abbottabad",
}

_model = None
_model_path: Optional[Path] = None


def normalize_city(value: Any) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "Unknown"
    text = str(value).strip()
    if not text:
        return "Unknown"
    key = text.upper()
    if key in KNOWN_CITIES:
        return KNOWN_CITIES[key]
    # Title-case unknown-but-present spellings without inventing a different city
    return text[:1].upper() + text[1:] if text else "Unknown"


def normalize_source(value: Any) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "Unknown"
    text = re.sub(r"\s+", " ", str(value).strip())
    return text if text else "Unknown"


def normalize_area(value: Any) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "Unknown"
    text = re.sub(r"\s+", " ", str(value).strip())
    return text if text else "Unknown"


def normalize_property_type(value: Any) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "Unknown"
    text = re.sub(r"\s+", " ", str(value).strip())
    return text if text else "Unknown"


def clean_leads_frame(df: pd.DataFrame) -> pd.DataFrame:
    """
    Shared cleaning for training and inference rows.

    - Parse created_at when present
    - Normalize city / source / area / property_type
    - Coerce binary flags and numerics
    - Validate converted when present (0/1 only)
    """
    out = df.copy()

    if "created_at" in out.columns:
        out["created_at"] = pd.to_datetime(out["created_at"], errors="coerce")

    if "source" in out.columns:
        out["source"] = out["source"].map(normalize_source)
    if "city" in out.columns:
        out["city"] = out["city"].map(normalize_city)
    if "area" in out.columns:
        out["area"] = out["area"].map(normalize_area)
    if "property_type" in out.columns:
        out["property_type"] = out["property_type"].map(normalize_property_type)

    for col in (
        "budget_pkr_lac",
        "bedrooms",
        "is_overseas",
        "referred_by_existing_client",
        "has_financing_approved",
    ):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    for col in ("is_overseas", "referred_by_existing_client", "has_financing_approved"):
        if col in out.columns:
            # Keep NaN for imputer; clip obvious non-binary noise to NaN
            bad = ~out[col].isna() & ~out[col].isin([0, 1, 0.0, 1.0])
            out.loc[bad, col] = np.nan

    if "converted" in out.columns:
        out["converted"] = pd.to_numeric(out["converted"], errors="coerce")
        invalid = ~out["converted"].isna() & ~out["converted"].isin([0, 1, 0.0, 1.0])
        if invalid.any():
            raise ValueError(
                f"converted must be binary 0/1; found invalid values in "
                f"{int(invalid.sum())} rows"
            )
        out["converted"] = out["converted"].astype("Int64")

    return out


def dedupe_leads(df: pd.DataFrame) -> pd.DataFrame:
    """Keep one row per crm_record_hash: earliest created_at, then lead_id."""
    if "crm_record_hash" not in df.columns:
        return df.copy()
    ordered = df.sort_values(
        by=["created_at", "lead_id"],
        ascending=[True, True],
        kind="mergesort",
    )
    return ordered.drop_duplicates(subset=["crm_record_hash"], keep="first").reset_index(
        drop=True
    )


def leads_to_feature_frame(records: pd.DataFrame | list[dict] | dict) -> pd.DataFrame:
    """Build a feature DataFrame with the exact training column order."""
    if isinstance(records, dict):
        frame = pd.DataFrame([records])
    elif isinstance(records, list):
        frame = pd.DataFrame(records)
    else:
        frame = records.copy()

    frame = clean_leads_frame(frame)

    # Ensure all expected columns exist
    for col in FEATURE_COLUMNS:
        if col not in frame.columns:
            frame[col] = np.nan

    return frame[FEATURE_COLUMNS]


def load_model(model_path: Optional[Path | str] = None):
    """Load (and cache) the persisted Pipeline."""
    global _model, _model_path
    path = Path(model_path) if model_path else DEFAULT_MODEL_PATH
    if _model is not None and _model_path == path:
        return _model
    if not path.exists():
        raise FileNotFoundError(
            f"Model not found at {path}. Run: python scripts/train_model.py"
        )
    _model = joblib.load(path)
    _model_path = path
    return _model


def score_lead(lead_details: dict) -> dict:
    """
    Score a single lead at intake time.

    Parameters
    ----------
    lead_details : dict
        Keys among FEATURE_COLUMNS (missing keys treated as unknown / imputed).

    Returns
    -------
    dict with probability (0-1), percentage, and disclaimer.
    """
    if not isinstance(lead_details, dict):
        raise TypeError("lead_details must be a dict")

    model = load_model()
    X = leads_to_feature_frame(lead_details)

    # predict_proba column 1 = P(converted=1)
    proba = float(model.predict_proba(X)[0, 1])
    # Numerical safety
    proba = float(min(1.0, max(0.0, proba)))

    return {
        "conversion_probability": proba,
        "conversion_probability_pct": round(proba * 100.0, 2),
        "label": "model_estimate",
        "disclaimer": (
            "Model estimate only - not a guarantee of conversion. "
            "Trained for intake-time prioritization; excludes post-intake "
            "activity and token payment."
        ),
        "features_used": FEATURE_COLUMNS,
    }
