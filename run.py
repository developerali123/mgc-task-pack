"""
MGC assessment — Part 4 minimal Flask UI.

Wires Part 1 (document assistant) and Part 3 (lead scoring). Business logic
stays in app.document_assistant / app.lead_scoring — routes only adapt HTTP.
"""

from __future__ import annotations

import traceback
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, url_for

from app.document_assistant import answer_question
from app.lead_scoring import (
    DEFAULT_MODEL_PATH,
    FEATURE_COLUMNS,
    score_lead,
)

_ROOT = Path(__file__).resolve().parent
app = Flask(__name__, template_folder=str(_ROOT / "templates"))
app.secret_key = "mgc-assessment-local-dev-only"

# Fields the HTML form may submit for scoring (intake-time only)
SCORE_FORM_FIELDS = FEATURE_COLUMNS
FORBIDDEN_SCORE_FIELDS = frozenset(
    {
        "converted",
        "calls_made",
        "total_call_seconds",
        "whatsapp_replies",
        "site_visits",
        "token_amount_received_pkr",
        "first_response_minutes",
        "agent_experience_years",
        "lead_id",
        "crm_record_hash",
        "created_at",
    }
)

SOURCE_CHOICES = [
    "Facebook Ads",
    "Property Portal",
    "Google Search",
    "Instagram",
    "Referral",
    "Walk-in",
    "WhatsApp Campaign",
    "Expo Stall",
    "Billboard",
]

PROPERTY_TYPE_CHOICES = [
    "Apartment",
    "Plot",
    "Villa",
    "Commercial Shop",
    "Penthouse",
    "Farmhouse",
]


def _template_context(**extra):
    ctx = {
        "source_choices": SOURCE_CHOICES,
        "property_type_choices": PROPERTY_TYPE_CHOICES,
        "feature_columns": FEATURE_COLUMNS,
        "model_path": str(DEFAULT_MODEL_PATH),
        "model_present": DEFAULT_MODEL_PATH.exists(),
    }
    ctx.update(extra)
    return ctx


@app.get("/")
def home():
    return render_template("index.html", **_template_context())


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model_present": DEFAULT_MODEL_PATH.exists(),
        "model_path": str(DEFAULT_MODEL_PATH),
    }


@app.post("/ask")
def ask():
    question = (request.form.get("question") or "").strip()
    if not question:
        flash("Please enter a question.", "error")
        return redirect(url_for("home"))

    try:
        answer = answer_question(question)
    except Exception as exc:  # noqa: BLE001 — surface safely to salesperson UI
        app.logger.exception("ask failed")
        return render_template(
            "index.html",
            **_template_context(
                ask_question=question,
                ask_error=(
                    "Could not answer that question due to an internal error. "
                    "No fabricated answer was generated."
                ),
                ask_error_detail=str(exc),
            ),
        )

    sources = [
        {
            "filename": s.filename,
            "document_title": s.document_title,
            "section": s.section,
            "excerpt": s.excerpt,
            "citation": s.citation(),
        }
        for s in answer.sources
    ]
    return render_template(
        "index.html",
        **_template_context(
            ask_question=question,
            ask_answer=answer.text,
            ask_intent=answer.intent,
            ask_sources=sources,
        ),
    )


def _parse_optional_float(raw: str, field: str):
    text = (raw or "").strip()
    if text == "":
        return None
    try:
        return float(text)
    except ValueError as exc:
        raise ValueError(f"{field} must be a number (or left blank).") from exc


def _parse_binary_flag(raw: str, field: str) -> int:
    text = (raw or "").strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return 1
    if text in {"0", "false", "no", "n", ""}:
        return 0
    raise ValueError(f"{field} must be 0 or 1.")


def build_lead_from_form(form) -> dict:
    """Validate intake-time fields only; reject post-outcome columns."""
    for key in form:
        if key in FORBIDDEN_SCORE_FIELDS:
            raise ValueError(
                f"Field '{key}' is not allowed for intake scoring "
                "(post-intake / outcome / identifier)."
            )

    lead: dict = {}

    source = (form.get("source") or "").strip()
    if not source:
        raise ValueError("source is required.")
    lead["source"] = source

    city = (form.get("city") or "").strip()
    if not city:
        raise ValueError("city is required.")
    lead["city"] = city

    # Optional categoricals
    area = (form.get("area") or "").strip()
    lead["area"] = area if area else None

    property_type = (form.get("property_type") or "").strip()
    if not property_type:
        raise ValueError("property_type is required.")
    lead["property_type"] = property_type

    lead["budget_pkr_lac"] = _parse_optional_float(
        form.get("budget_pkr_lac", ""), "budget_pkr_lac"
    )
    lead["bedrooms"] = _parse_optional_float(form.get("bedrooms", ""), "bedrooms")

    lead["is_overseas"] = _parse_binary_flag(form.get("is_overseas", "0"), "is_overseas")
    lead["referred_by_existing_client"] = _parse_binary_flag(
        form.get("referred_by_existing_client", "0"), "referred_by_existing_client"
    )
    lead["has_financing_approved"] = _parse_binary_flag(
        form.get("has_financing_approved", "0"), "has_financing_approved"
    )

    # Never pass through unexpected keys from the form
    return {k: lead[k] for k in FEATURE_COLUMNS if k in lead}


@app.post("/score")
def score():
    form_snapshot = {k: request.form.get(k, "") for k in SCORE_FORM_FIELDS}

    try:
        lead = build_lead_from_form(request.form)
    except ValueError as exc:
        return render_template(
            "index.html",
            **_template_context(
                score_form=form_snapshot,
                score_error=str(exc),
            ),
        )

    if not DEFAULT_MODEL_PATH.exists():
        return render_template(
            "index.html",
            **_template_context(
                score_form=form_snapshot,
                score_error=(
                    f"Scoring model not found at {DEFAULT_MODEL_PATH}. "
                    "Run: python scripts/train_model.py "
                    "No probability was fabricated."
                ),
            ),
        )

    try:
        result = score_lead(lead)
    except FileNotFoundError as exc:
        return render_template(
            "index.html",
            **_template_context(
                score_form=form_snapshot,
                score_error=f"{exc} No probability was fabricated.",
            ),
        )
    except Exception as exc:  # noqa: BLE001
        app.logger.error("score failed: %s", traceback.format_exc())
        return render_template(
            "index.html",
            **_template_context(
                score_form=form_snapshot,
                score_error=(
                    "Scoring failed due to an internal error. "
                    "No probability was fabricated. "
                    f"Detail: {exc}"
                ),
            ),
        )

    return render_template(
        "index.html",
        **_template_context(
            score_form=form_snapshot,
            score_result=result,
        ),
    )


def create_app() -> Flask:
    return app


if __name__ == "__main__":
    # Local assessment entry point
    port = 5000
    print(f"MGC sales helper: http://127.0.0.1:{port}/")
    print(f"Health check:     http://127.0.0.1:{port}/health")
    print(f"Model present:    {DEFAULT_MODEL_PATH.exists()} ({DEFAULT_MODEL_PATH})")
    app.run(host="127.0.0.1", port=port, debug=True)
