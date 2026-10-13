"""Part 1 — six required Q&A scenarios + pricing Decimal checks."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.document_assistant import answer_question
from app.pricing import calculate_price, lookup_base_price, PricingError, format_pkr


# Exact expected amounts (Decimal, whole PKR)
BASE_2BED_B = Decimal("22425000")
BASE_2BED_CORNER_B = Decimal("26855000")
BASE_3BED_EXEC_B = Decimal("39480000")

# Corner floor 15 Margalla: base + 4% + 3% + 6% of base
CORNER_FLOOR = BASE_2BED_CORNER_B * Decimal("0.04")  # 1,074,200
CORNER_CORNER = BASE_2BED_CORNER_B * Decimal("0.03")  # 805,650
CORNER_MARGALLA = BASE_2BED_CORNER_B * Decimal("0.06")  # 1,611,300
CORNER_TOTAL = BASE_2BED_CORNER_B + CORNER_FLOOR + CORNER_CORNER + CORNER_MARGALLA
# 30,346,150

DISC_50 = BASE_3BED_EXEC_B * Decimal("0.06")  # 2,368,800
DISC_OS = BASE_3BED_EXEC_B * Decimal("0.02")  # 789,600
PRICE_AFTER_DISC = BASE_3BED_EXEC_B - DISC_50 - DISC_OS  # 36,321,600
BOOKING_10 = PRICE_AFTER_DISC * Decimal("0.10")  # 3,632,160


class TestPricingEngine:
    def test_base_2bed_block_b(self):
        assert lookup_base_price("B", "2-Bed Standard") == BASE_2BED_B

    def test_stacked_corner_margalla_floor_15(self):
        q = calculate_price(
            "B", "2-Bed Corner", floor=15, is_corner=True, is_margalla=True
        )
        assert q.base_price == BASE_2BED_CORNER_B
        assert q.premiums.floor_amount == Decimal("1074200")
        assert q.premiums.corner_amount == Decimal("805650")
        assert q.premiums.margalla_amount == Decimal("1611300")
        assert q.premiums.total_rate == Decimal("0.13")
        assert q.final_price == Decimal("30346150")
        assert q.discounts.total_amount == Decimal("0")

    def test_overseas_50_upfront_3bed(self):
        q = calculate_price(
            "B",
            "3-Bed Executive",
            discount_50_upfront=True,
            discount_overseas=True,
        )
        assert q.base_price == BASE_3BED_EXEC_B
        assert q.discounts.upfront_50_amount == Decimal("2368800")
        assert q.discounts.overseas_amount == Decimal("789600")
        assert q.final_price == Decimal("36321600")
        assert q.booking_token == Decimal("3632160")
        assert q.premiums.total_amount == Decimal("0")

    def test_discounts_do_not_apply_to_premiums(self):
        q = calculate_price(
            "B",
            "2-Bed Standard",
            floor=15,
            is_margalla=True,
            discount_50_upfront=True,
        )
        # Discount only on base; premium = 4%+6% of full base
        expected_disc = BASE_2BED_B * Decimal("0.06")
        expected_prem = BASE_2BED_B * Decimal("0.10")
        assert q.discounts.total_amount == expected_disc
        assert q.premiums.total_amount == expected_prem
        assert q.final_price == BASE_2BED_B - expected_disc + expected_prem

    def test_cannot_combine_cash_and_50(self):
        with pytest.raises(PricingError):
            calculate_price(
                "B",
                "2-Bed Standard",
                discount_50_upfront=True,
                discount_full_cash=True,
            )

    def test_margalla_not_for_studio(self):
        with pytest.raises(PricingError):
            calculate_price("A", "Studio", is_margalla=True)


class TestSixRequiredQuestions:
    def test_01_base_price_2bed_block_b(self):
        ans = answer_question("What's the base price of a 2-bed in Block B?")
        assert ans.intent == "base_price_2bed_b"
        assert "22,425,000" in ans.text or "22425000" in ans.text.replace(",", "")
        assert any(s.filename == "02_price_list_payment_plan.md" for s in ans.sources)
        assert any("Base Prices (Block B)" in s.section for s in ans.sources)
        assert format_pkr(BASE_2BED_B) in ans.text or "22,425,000" in ans.text

    def test_02_stacked_premiums_2bed_corner_floor_15(self):
        ans = answer_question(
            "What's the total for a Margalla-facing corner unit on floor 15, "
            "2-bed Block B?"
        )
        assert ans.intent == "stacked_2bed_corner_margalla"
        assert ans.price_details is not None
        assert ans.price_details["final_price"] == "30346150"
        assert "30,346,150" in ans.text
        assert "26,855,000" in ans.text
        filenames = {s.filename for s in ans.sources}
        assert "02_price_list_payment_plan.md" in filenames
        sections = {s.section for s in ans.sources}
        assert "Base Prices (Block B)" in sections
        assert "Location Premiums" in sections

    def test_03_overseas_50_upfront_3bed_executive(self):
        ans = answer_question(
            "An overseas Pakistani buyer pays 50% upfront on a 3-Bed Executive — "
            "what's the price after discounts, and what's due at booking?"
        )
        assert ans.intent == "overseas_3bed_50_upfront"
        assert ans.price_details is not None
        assert ans.price_details["final_price"] == "36321600"
        assert ans.price_details["booking_token"] == "3632160"
        assert "36,321,600" in ans.text
        assert "3,632,160" in ans.text
        # Distinguish booking from 50% upfront condition
        assert "10%" in ans.text
        assert "50%" in ans.text
        assert "not" in ans.text.lower()
        sections = {s.section for s in ans.sources}
        assert "Discounts" in sections
        assert "Standard Payment Plan (4 years)" in sections
        assert "Base Prices (Block B)" in sections

    def test_04_transfer_fee_conflict(self):
        ans = answer_question("What's the transfer fee?")
        assert ans.intent == "transfer_fee_conflict"
        assert "2%" in ans.text
        assert "2.5%" in ans.text
        # Must not silently pick one
        assert "disagree" in ans.text.lower() or "conflict" in ans.text.lower() or (
            "2%" in ans.text and "2.5%" in ans.text
        )
        filenames = {s.filename for s in ans.sources}
        assert "02_price_list_payment_plan.md" in filenames
        assert "03_booking_policy_faq.md" in filenames
        sections = {s.section for s in ans.sources}
        assert "Other Charges" in sections
        assert "Transfers" in sections
        assert "confirm" in ans.text.lower()

    def test_05_rental_yield_unavailable(self):
        ans = answer_question("What's the rental yield on a 1-bed?")
        assert ans.intent == "rental_yield_unavailable"
        assert "marketing manager" in ans.text.lower()
        # Must not invent a percentage
        assert "%" not in ans.text.split("marketing")[0] or "projection" in ans.text.lower()
        # Stronger: no invented yield number like "5%" or "8%" as an answer
        import re

        invented = re.findall(r"\b\d+(?:\.\d+)?%\b", ans.text)
        # Allow no yield percentages at all in the refusal
        assert invented == []
        assert any(s.filename == "03_booking_policy_faq.md" for s in ans.sources)
        assert any("Frequently Asked" in s.section for s in ans.sources)

    def test_06_anchor_tenant_unconfirmed(self):
        ans = answer_question("Who is the anchor tenant?")
        assert ans.intent == "anchor_tenant_unconfirmed"
        assert "no anchor tenant has been confirmed" in ans.text.lower()
        assert any(s.filename == "01_mgc_aurora_heights_brochure.md" for s in ans.sources)
        assert any("Commercial Podium" in s.section for s in ans.sources)


class TestAnswerApi:
    def test_answer_question_returns_structured_sources(self):
        ans = answer_question("What's the transfer fee?")
        assert isinstance(ans.text, str)
        assert len(ans.sources) >= 2
        for src in ans.sources:
            assert src.filename.endswith(".md")
            assert src.document_title
            assert src.section
            assert src.citation()
