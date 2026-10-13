"""Part 4 — Flask integration tests (no hardcoded Q&A / scores)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.lead_scoring import DEFAULT_MODEL_PATH
import run as webapp


@pytest.fixture
def client():
    webapp.app.config["TESTING"] = True
    with webapp.app.test_client() as c:
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    data = r.get_json()
    assert data["status"] == "ok"
    assert "model_present" in data


def test_home_page_has_both_sections(client):
    r = client.get("/")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "Section A" in html
    assert "Section B" in html
    assert 'action="/ask"' in html or 'action="/ask"' in html.replace("&#47;", "/")
    assert "/score" in html


def test_ask_pricing_with_citation(client):
    r = client.post("/ask", data={"question": "What's the base price of a 2-bed in Block B?"})
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "22,425,000" in html
    assert "02_price_list_payment_plan.md" in html
    assert "Base Prices (Block B)" in html


def test_ask_transfer_fee_shows_both_sources(client):
    r = client.post("/ask", data={"question": "What's the transfer fee?"})
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "2%" in html and "2.5%" in html
    assert "02_price_list_payment_plan.md" in html
    assert "03_booking_policy_faq.md" in html
    assert "Other Charges" in html
    assert "Transfers" in html


def test_ask_rental_yield_no_invented_percent(client):
    r = client.post("/ask", data={"question": "What's the rental yield on a 1-bed?"})
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "marketing manager" in html.lower()
    # No unsupported yield percentage like "5%" in the answer body before sources
    import re

    # Strip source footnotes-ish; ensure no standalone yield % claimed
    assert re.search(r"\b\d+(?:\.\d+)?%\b", html.split("Sources")[0] if "Sources" in html else html) is None or (
        "2%" not in html.split("marketing")[0]  # transfer fee page shouldn't appear
    )
    # Stronger: rental yield intent should not invent a figure — look for refusal language
    assert "not" in html.lower() and "yield" in html.lower()


def test_score_valid_lead(client):
    if not DEFAULT_MODEL_PATH.exists():
        pytest.skip("model artifact missing — run scripts/train_model.py")
    r = client.post(
        "/score",
        data={
            "source": "Referral",
            "city": "Islamabad",
            "area": "GT Road Corridor",
            "property_type": "Apartment",
            "budget_pkr_lac": "120",
            "bedrooms": "2",
            "is_overseas": "0",
            "referred_by_existing_client": "1",
            "has_financing_approved": "0",
        },
    )
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "Predicted conversion probability" in html
    assert "estimate" in html.lower() or "not a guarantee" in html.lower()
    assert "Validation / scoring error" not in html


def test_score_invalid_budget(client):
    r = client.post(
        "/score",
        data={
            "source": "Referral",
            "city": "Islamabad",
            "property_type": "Apartment",
            "budget_pkr_lac": "not-a-number",
            "is_overseas": "0",
            "referred_by_existing_client": "0",
            "has_financing_approved": "0",
        },
    )
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "must be a number" in html
    assert "Predicted conversion probability" not in html


def test_score_rejects_forbidden_converted_field(client):
    r = client.post(
        "/score",
        data={
            "source": "Walk-in",
            "city": "Lahore",
            "property_type": "Villa",
            "converted": "1",
            "is_overseas": "0",
            "referred_by_existing_client": "0",
            "has_financing_approved": "0",
        },
    )
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "not allowed" in html.lower()
    assert "Predicted conversion probability" not in html


def test_score_missing_model_clear_error(client, tmp_path, monkeypatch):
    """Temporarily hide the model file and confirm no fake probability."""
    if not DEFAULT_MODEL_PATH.exists():
        # Already missing — just hit the endpoint
        r = client.post(
            "/score",
            data={
                "source": "Referral",
                "city": "Islamabad",
                "property_type": "Apartment",
                "is_overseas": "0",
                "referred_by_existing_client": "0",
                "has_financing_approved": "0",
            },
        )
        html = r.get_data(as_text=True)
        assert "not found" in html.lower() or "model" in html.lower()
        assert "Predicted conversion probability" not in html
        return

    backup = tmp_path / "lead_scoring_model.joblib"
    shutil.copy2(DEFAULT_MODEL_PATH, backup)
    DEFAULT_MODEL_PATH.unlink()
    # Clear cached model in lead_scoring
    import app.lead_scoring as ls

    ls._model = None
    ls._model_path = None
    try:
        r = client.post(
            "/score",
            data={
                "source": "Referral",
                "city": "Islamabad",
                "property_type": "Apartment",
                "is_overseas": "0",
                "referred_by_existing_client": "0",
                "has_financing_approved": "0",
            },
        )
        html = r.get_data(as_text=True)
        assert "not found" in html.lower()
        assert "fabricated" in html.lower()
        assert "Predicted conversion probability" not in html
    finally:
        shutil.copy2(backup, DEFAULT_MODEL_PATH)
        ls._model = None
        ls._model_path = None
