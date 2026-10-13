"""Smoke test intended to run inside a fresh venv."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.document_assistant import answer_question
from app.lead_scoring import score_lead
import flask  # noqa: F401
import pandas  # noqa: F401
import sklearn  # noqa: F401
import joblib  # noqa: F401

ans = answer_question("What's the transfer fee?")
print("venv_ask", ans.intent, len(ans.sources))
assert ans.intent == "transfer_fee_conflict"
assert len(ans.sources) >= 2

result = score_lead(
    {
        "source": "Walk-in",
        "city": "Lahore",
        "property_type": "Apartment",
        "is_overseas": 0,
        "referred_by_existing_client": 0,
        "has_financing_approved": 0,
    }
)
print("venv_score", round(result["conversion_probability"], 4))
assert 0.0 <= result["conversion_probability"] <= 1.0
print("deps_ok")
