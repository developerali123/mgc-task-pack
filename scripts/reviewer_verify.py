"""Independent reviewer verification harness (no fabricated results)."""

from __future__ import annotations

import json
import re
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.document_assistant import answer_question
from app.lead_scoring import FEATURE_COLUMNS, score_lead, DEFAULT_MODEL_PATH
from app.pricing import calculate_price


def check_arithmetic() -> list[str]:
    fails = []
    q = calculate_price("B", "2-Bed Corner", floor=15, is_corner=True, is_margalla=True)
    if q.base_price != Decimal("26855000"):
        fails.append(f"corner base {q.base_price}")
    if q.final_price != Decimal("26855000") * Decimal("1.13"):
        fails.append(f"corner total {q.final_price}")
    if q.final_price != Decimal("30346150"):
        fails.append(f"corner expected 30346150 got {q.final_price}")

    q2 = calculate_price(
        "B", "3-Bed Executive", discount_50_upfront=True, discount_overseas=True
    )
    if q2.base_price != Decimal("39480000"):
        fails.append(f"exec base {q2.base_price}")
    if q2.final_price != Decimal("39480000") * Decimal("0.92"):
        fails.append(f"exec discounted {q2.final_price}")
    if q2.final_price != Decimal("36321600"):
        fails.append(f"exec expected 36321600 got {q2.final_price}")
    if q2.booking_token != Decimal("3632160"):
        fails.append(f"token expected 3632160 got {q2.booking_token}")
    return fails


def check_qa() -> list[str]:
    fails = []
    cases = [
        (
            "What's the base price of a 2-bed in Block B?",
            "base_price_2bed_b",
            ["22,425,000"],
            ["02_price_list_payment_plan.md"],
            ["Base Prices (Block B)"],
        ),
        (
            "What's the total for a Margalla-facing corner unit on floor 15, 2-bed Block B?",
            "stacked_2bed_corner_margalla",
            ["30,346,150"],
            ["02_price_list_payment_plan.md"],
            ["Location Premiums"],
        ),
        (
            "An overseas Pakistani buyer pays 50% upfront on a 3-Bed Executive — "
            "what's the price after discounts, and what's due at booking?",
            "overseas_3bed_50_upfront",
            ["36,321,600", "3,632,160", "10%", "50%"],
            ["02_price_list_payment_plan.md"],
            ["Discounts", "Standard Payment Plan (4 years)"],
        ),
        (
            "What's the transfer fee?",
            "transfer_fee_conflict",
            ["2%", "2.5%"],
            ["02_price_list_payment_plan.md", "03_booking_policy_faq.md"],
            ["Other Charges", "Transfers"],
        ),
        (
            "What's the rental yield on a 1-bed?",
            "rental_yield_unavailable",
            ["marketing manager"],
            ["03_booking_policy_faq.md"],
            ["Frequently Asked"],
        ),
        (
            "Who is the anchor tenant?",
            "anchor_tenant_unconfirmed",
            ["no anchor tenant has been confirmed"],
            ["01_mgc_aurora_heights_brochure.md"],
            ["Commercial Podium"],
        ),
    ]
    for q, intent, needles, files, sections in cases:
        ans = answer_question(q)
        if ans.intent != intent:
            fails.append(f"{intent}: got intent {ans.intent}")
        for n in needles:
            if n.lower() not in ans.text.lower():
                fails.append(f"{intent}: missing {n!r}")
        fns = {s.filename for s in ans.sources}
        secs = {s.section for s in ans.sources}
        for f in files:
            if f not in fns:
                fails.append(f"{intent}: missing file {f}")
        for s in sections:
            if s not in secs:
                fails.append(f"{intent}: missing section {s}")
        if intent == "rental_yield_unavailable" and re.findall(
            r"\b\d+(?:\.\d+)?%\b", ans.text
        ):
            fails.append("rental yield invented percentage")
        if intent == "overseas_3bed_50_upfront":
            # Must distinguish token from 50% eligibility
            if "not" not in ans.text.lower() or "booking" not in ans.text.lower():
                fails.append("overseas: weak token vs 50% distinction")
    return fails


def check_ml_artifacts() -> list[str]:
    fails = []
    leak = {
        "token_amount_received_pkr",
        "calls_made",
        "total_call_seconds",
        "whatsapp_replies",
        "site_visits",
        "first_response_minutes",
        "agent_experience_years",
        "converted",
    }
    if leak & set(FEATURE_COLUMNS):
        fails.append(f"leak features in model: {leak & set(FEATURE_COLUMNS)}")
    metrics_path = ROOT / "reports" / "model_metrics.json"
    if not metrics_path.exists():
        fails.append("missing model_metrics.json")
        return fails
    m = json.loads(metrics_path.read_text(encoding="utf-8"))
    if m["split"]["train_end_created_at"] >= m["split"]["test_start_created_at"]:
        fails.append("chronological split invalid")
    if set(m["feature_columns"]) & leak:
        fails.append("metrics feature list has leakage")
    if "primary_metric" not in m or m["primary_metric"].get("value") is None:
        fails.append("missing AP metric")
    if "no_skill_baseline" not in m.get("primary_metric", {}):
        fails.append("missing no-skill baseline")
    top = m.get("business_metric_top_100", {})
    if top.get("conversions_in_top_k") is None:
        fails.append("missing top-100 conversions")
    if not DEFAULT_MODEL_PATH.exists():
        fails.append("missing joblib model")
    else:
        r = score_lead(
            {
                "source": "Referral",
                "city": "Islamabad",
                "property_type": "Apartment",
                "budget_pkr_lac": 120,
                "bedrooms": 2,
                "is_overseas": 0,
                "referred_by_existing_client": 1,
                "has_financing_approved": 0,
            }
        )
        if not (0.0 <= r["conversion_probability"] <= 1.0):
            fails.append("score out of range")
    return fails


def main() -> int:
    sections = {
        "arithmetic": check_arithmetic(),
        "qa_citations": check_qa(),
        "ml_contract": check_ml_artifacts(),
    }
    code = 0
    for name, fails in sections.items():
        if fails:
            code = 1
            print(f"FAIL {name}:")
            for f in fails:
                print(f"  - {f}")
        else:
            print(f"PASS {name}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
