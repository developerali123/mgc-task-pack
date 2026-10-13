"""Quick Part 1 BRIEF-case audit (citations + Decimal)."""

from __future__ import annotations

import re
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.document_assistant import answer_question
from app.pricing import calculate_price, lookup_base_price


def main() -> int:
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
            ["Location Premiums", "Base Prices (Block B)"],
        ),
        (
            "An overseas Pakistani buyer pays 50% upfront on a 3-Bed Executive — "
            "what's the price after discounts, and what's due at booking?",
            "overseas_3bed_50_upfront",
            ["36,321,600", "3,632,160"],
            ["02_price_list_payment_plan.md"],
            ["Discounts", "Standard Payment Plan (4 years)", "Base Prices (Block B)"],
        ),
        (
            "What's the transfer fee?",
            "transfer_fee_conflict",
            ["2%", "2.5%", "disagree"],
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

    failures = 0
    for question, intent, needles, files, sections in cases:
        ans = answer_question(question)
        print(f"[{intent}] intent={ans.intent}")
        if ans.intent != intent:
            print("  FAIL intent")
            failures += 1
        text_l = ans.text.lower()
        for needle in needles:
            if needle.lower() not in text_l:
                print(f"  FAIL missing {needle!r}")
                failures += 1
        fns = {s.filename for s in ans.sources}
        secs = {s.section for s in ans.sources}
        for f in files:
            if f not in fns:
                print(f"  FAIL missing file {f}")
                failures += 1
        for sec in sections:
            if sec not in secs:
                print(f"  FAIL missing section {sec}")
                failures += 1
        if intent == "rental_yield_unavailable" and re.findall(
            r"\b\d+(?:\.\d+)?%\b", ans.text
        ):
            print("  FAIL invented yield percentage")
            failures += 1

    assert isinstance(lookup_base_price("B", "2-Bed Standard"), Decimal)
    quote = calculate_price(
        "B", "2-Bed Standard", floor=15, is_margalla=True, discount_50_upfront=True
    )
    assert quote.discounts.total_amount == Decimal("22425000") * Decimal("0.06")
    assert quote.premiums.total_amount == Decimal("22425000") * Decimal("0.10")
    assert quote.final_price == (
        Decimal("22425000") - quote.discounts.total_amount + quote.premiums.total_amount
    )
    print("Decimal + discount-on-base-only: OK")
    print("PART1_RESULT", "PASS" if failures == 0 else f"FAIL ({failures})")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
