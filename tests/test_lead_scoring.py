"""Part 3 — intake feature contract and leakage guards."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.lead_scoring import (
    DEFAULT_MODEL_PATH,
    EXCLUDED_COLUMNS,
    FEATURE_COLUMNS,
    score_lead,
)


LEAKY = [
    "token_amount_received_pkr",
    "calls_made",
    "total_call_seconds",
    "whatsapp_replies",
    "site_visits",
    "first_response_minutes",
    "agent_experience_years",
    "converted",
    "lead_id",
    "crm_record_hash",
]


def test_feature_columns_exclude_leakage():
    for col in LEAKY:
        assert col not in FEATURE_COLUMNS
        assert col in EXCLUDED_COLUMNS or col == "converted"


@pytest.mark.skipif(not DEFAULT_MODEL_PATH.exists(), reason="model not trained")
def test_score_lead_probability_bounds():
    result = score_lead(
        {
            "source": "Referral",
            "city": "ISB",
            "property_type": "Apartment",
            "budget_pkr_lac": 100,
            "bedrooms": 2,
            "is_overseas": 0,
            "referred_by_existing_client": 1,
            "has_financing_approved": 0,
        }
    )
    assert 0.0 <= result["conversion_probability"] <= 1.0
    assert result["label"] == "model_estimate"
    assert "guarantee" in result["disclaimer"].lower() or "estimate" in result[
        "disclaimer"
    ].lower()
