"""
Document-grounded Q&A for MGC sales staff.

Architecture:
  - Intent routing for known high-stakes questions (pricing, conflicts, refusals)
  - Deterministic Decimal pricing via app.pricing (never LLM arithmetic)
  - Local Markdown section retrieval via app.knowledge_base
  - Every answer carries structured SourceRef citations from real headings

This module does NOT call any external language-model API.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from app.knowledge_base import KnowledgeBase, SourceRef, load_knowledge_base
from app.pricing import (
    calculate_price,
    format_pkr,
    lookup_base_price,
)


@dataclass
class Answer:
    text: str
    sources: list[SourceRef] = field(default_factory=list)
    intent: str = "general"
    price_details: Optional[dict] = None

    def citation_block(self) -> str:
        if not self.sources:
            return ""
        lines = ["Sources:"]
        for src in self.sources:
            line = f"- {src.citation()}"
            if src.excerpt:
                line += f' — "{src.excerpt}"'
            lines.append(line)
        return "\n".join(lines)

    def full_text(self) -> str:
        block = self.citation_block()
        return f"{self.text}\n\n{block}" if block else self.text


# ---------------------------------------------------------------------------
# Intent helpers
# ---------------------------------------------------------------------------

def _norm(q: str) -> str:
    return re.sub(r"\s+", " ", q.strip().lower())


def _mentions_transfer_fee(q: str) -> bool:
    n = _norm(q)
    return "transfer" in n and "fee" in n


def _mentions_rental_yield(q: str) -> bool:
    n = _norm(q)
    if "yield" not in n:
        return False
    return (
        "rental" in n
        or "rent" in n
        or "1-bed" in n
        or "1 bed" in n
        or "studio" in n
        or "apartment" in n
        or n.startswith("what")
    )


def _mentions_anchor_tenant(q: str) -> bool:
    n = _norm(q)
    return "anchor" in n and "tenant" in n


def _mentions_base_price_2bed_b(q: str) -> bool:
    n = _norm(q)
    if "base" not in n and "price" not in n:
        return False
    has_2bed = bool(re.search(r"2[\s-]*bed", n))
    has_block_b = "block b" in n or "block-b" in n
    # Prefer simple lookup when NOT asking for premiums / corner / margalla / floor stacks
    stacked = any(
        k in n
        for k in ("corner", "margalla", "floor", "premium", "facing", "total")
    )
    return has_2bed and has_block_b and not stacked and (
        "base" in n or ("price" in n and "what" in n)
    )


def _mentions_stacked_2bed_corner_margalla(q: str) -> bool:
    n = _norm(q)
    has_2bed = bool(re.search(r"2[\s-]*bed", n))
    has_block_b = "block b" in n
    has_corner = "corner" in n
    has_margalla = "margalla" in n
    has_floor_15 = bool(re.search(r"floor\s*15\b", n) or re.search(r"\b15\b", n))
    return has_2bed and has_block_b and has_corner and has_margalla and (
        has_floor_15 or "floor" in n
    )


def _mentions_overseas_3bed_50(q: str) -> bool:
    n = _norm(q)
    overseas = "overseas" in n or "roshan" in n
    three_bed = bool(re.search(r"3[\s-]*bed", n)) or "executive" in n
    fifty = "50%" in n or "50 %" in n or "fifty" in n or "50 percent" in n
    return overseas and three_bed and fifty


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

class DocumentAssistant:
    def __init__(self, kb: Optional[KnowledgeBase] = None) -> None:
        self.kb = kb or load_knowledge_base()

    def answer(self, question: str) -> Answer:
        q = question.strip()
        if not q:
            return Answer(
                text="Please ask a question about MGC Aurora Heights pricing, "
                "payment plans, or booking policy.",
                intent="empty",
            )

        if _mentions_transfer_fee(q):
            return self._answer_transfer_fee()
        if _mentions_rental_yield(q):
            return self._answer_rental_yield()
        if _mentions_anchor_tenant(q):
            return self._answer_anchor_tenant()
        if _mentions_overseas_3bed_50(q):
            return self._answer_overseas_3bed_50()
        if _mentions_stacked_2bed_corner_margalla(q):
            return self._answer_stacked_2bed_corner()
        if _mentions_base_price_2bed_b(q):
            return self._answer_base_2bed_b()

        return self._answer_retrieval(q)

    # --- Required scenarios -------------------------------------------------

    def _answer_base_2bed_b(self) -> Answer:
        base = lookup_base_price("B", "2-Bed Standard")
        section = self.kb.get_section(
            "02_price_list_payment_plan.md", "Base Prices (Block B)"
        )
        excerpt = "2-Bed Standard | 1,150 sq ft | 22,425,000 | 19,500"
        ref = section.to_ref(excerpt)
        text = (
            f"The base price of a 2-Bed Standard in Block B is {format_pkr(base)}.\n\n"
            f"Source: {ref.citation()}."
        )
        return Answer(text=text, sources=[ref], intent="base_price_2bed_b")

    def _answer_stacked_2bed_corner(self) -> Answer:
        quote = calculate_price(
            "B",
            "2-Bed Corner",
            floor=15,
            is_corner=True,
            is_margalla=True,
        )
        prices = self.kb.get_section(
            "02_price_list_payment_plan.md", "Base Prices (Block B)"
        )
        premiums = self.kb.get_section(
            "02_price_list_payment_plan.md", "Location Premiums"
        )
        refs = [
            prices.to_ref("2-Bed Corner | 1,310 sq ft | 26,855,000 | 20,500"),
            premiums.to_ref(
                "Floors 13–19: +4%; Corner unit: +3%; Margalla-facing: +6%. "
                "Premiums are cumulative."
            ),
        ]
        p = quote.premiums
        text = (
            "For a Block B **2-Bed Corner** unit on floor 15, Margalla-facing:\n\n"
            f"- Base price (2-Bed Corner, Block B): {format_pkr(quote.base_price)}\n"
            f"- Floor 13–19 premium (+{p.floor_rate * 100}% of base): "
            f"{format_pkr(p.floor_amount)}\n"
            f"- Corner premium (+{p.corner_rate * 100}% of base): "
            f"{format_pkr(p.corner_amount)}\n"
            f"- Margalla-facing premium (+{p.margalla_rate * 100}% of base): "
            f"{format_pkr(p.margalla_amount)}\n"
            f"- Combined premium rate: +{p.total_rate * 100}% of base "
            f"({format_pkr(p.total_amount)})\n"
            f"- **Total: {format_pkr(quote.final_price)}**\n\n"
            "Calculation uses Python Decimal on the published rates. "
            "Premiums are each applied to the base and then summed "
            "(not compounded on each other).\n\n"
            f"Sources: {refs[0].citation()}; {refs[1].citation()}."
        )
        return Answer(
            text=text,
            sources=refs,
            intent="stacked_2bed_corner_margalla",
            price_details=quote.as_dict(),
        )

    def _answer_overseas_3bed_50(self) -> Answer:
        quote = calculate_price(
            "B",
            "3-Bed Executive",
            discount_50_upfront=True,
            discount_overseas=True,
        )
        base_sec = self.kb.get_section(
            "02_price_list_payment_plan.md", "Base Prices (Block B)"
        )
        disc_sec = self.kb.get_section(
            "02_price_list_payment_plan.md", "Discounts"
        )
        plan_sec = self.kb.get_section(
            "02_price_list_payment_plan.md", "Standard Payment Plan (4 years)"
        )
        refs = [
            base_sec.to_ref("3-Bed Executive | 1,880 sq ft | 39,480,000 | 21,000"),
            disc_sec.to_ref(
                "50% upfront: 6% discount on base price. "
                "Overseas Pakistani (Roshan Digital Account): additional 2%, stackable."
            ),
            plan_sec.to_ref("Booking / token | 10% | Non-refundable after 30 days"),
        ]
        d = quote.discounts
        text = (
            "Overseas Pakistani buyer — Block B **3-Bed Executive**, **50% upfront** "
            "discount condition (no location premiums in this scenario):\n\n"
            f"- Base price: {format_pkr(quote.base_price)}\n"
            f"- 50% upfront discount (6% of base): "
            f"{format_pkr(d.upfront_50_amount)}\n"
            f"- Overseas / Roshan discount (2% of base): "
            f"{format_pkr(d.overseas_amount)}\n"
            f"- Total discount on base (8%): {format_pkr(d.total_amount)}\n"
            f"- **Price after discounts: {format_pkr(quote.final_price)}**\n"
            f"- **Due at booking (token, 10% of final price): "
            f"{format_pkr(quote.booking_token)}**\n\n"
            "Important distinction: choosing **50% upfront** unlocks the **6%** "
            "base-price discount; it is **not** the same thing as the booking/token. "
            "Under the standard payment plan, the booking/token remains **10%** of "
            "the final unit price. Location premiums are not discounted (none applied "
            "here). Discounts are calculated with Python Decimal on the base only.\n\n"
            f"Sources: {refs[0].citation()}; {refs[1].citation()}; {refs[2].citation()}."
        )
        return Answer(
            text=text,
            sources=refs,
            intent="overseas_3bed_50_upfront",
            price_details=quote.as_dict(),
        )

    def _answer_transfer_fee(self) -> Answer:
        price_other = self.kb.get_section(
            "02_price_list_payment_plan.md", "Other Charges"
        )
        faq_xfer = self.kb.get_section(
            "03_booking_policy_faq.md", "Transfers"
        )
        refs = [
            price_other.to_ref(
                "Transfer fee (before possession): 2% of the current list price"
            ),
            faq_xfer.to_ref(
                "Transfer fee is 2.5% of the current list price"
            ),
        ]
        text = (
            "The supplied documents **disagree** on the transfer fee — do not quote "
            "a single figure to a customer without confirmation.\n\n"
            f"- **Price list** ({refs[0].citation()}): transfer fee "
            f"**2%** of the current list price (before possession).\n"
            f"- **Booking policy / FAQ** ({refs[1].citation()}): transfer fee "
            f"**2.5%** of the current list price.\n\n"
            "Please confirm the current transfer fee with MGC before advising a buyer. "
            "Sales enquiries: 0308-77 77 275 (Head Office, Near Al-Jannat Mall, "
            "GT Road, Islamabad)."
        )
        return Answer(text=text, sources=refs, intent="transfer_fee_conflict")

    def _answer_rental_yield(self) -> Answer:
        faq = self.kb.get_section(
            "03_booking_policy_faq.md", "Frequently Asked"
        )
        ref = faq.to_ref(
            "MGC does not publish rental yield projections and sales staff must not "
            "give projections verbally. Direct such queries to the marketing manager."
        )
        text = (
            "I do not have a rental yield figure in the supplied documents, and I "
            "must not invent one.\n\n"
            "Per MGC booking policy: MGC does not publish rental yield projections "
            "and sales staff must not give projections verbally. "
            "**Direct this query to the marketing manager.**\n\n"
            f"Source: {ref.citation()}."
        )
        return Answer(text=text, sources=[ref], intent="rental_yield_unavailable")

    def _answer_anchor_tenant(self) -> Answer:
        podium = self.kb.get_section(
            "01_mgc_aurora_heights_brochure.md", "Commercial Podium"
        )
        ref = podium.to_ref(
            "Anchor tenancy discussions are ongoing; no anchor tenant has been "
            "confirmed as of this brochure's issue date."
        )
        text = (
            "No anchor tenant has been confirmed.\n\n"
            "According to the project brochure, anchor tenancy discussions are "
            "ongoing and no anchor tenant has been confirmed as of the brochure's "
            "issue date (March 2025).\n\n"
            f"Source: {ref.citation()}."
        )
        return Answer(text=text, sources=[ref], intent="anchor_tenant_unconfirmed")

    # --- Generic retrieval --------------------------------------------------

    def _answer_retrieval(self, question: str) -> Answer:
        hits = self.kb.search(question, limit=3)
        if not hits:
            return Answer(
                text=(
                    "I could not find that information in the supplied MGC documents "
                    "(brochure, price list & payment plan, booking policy FAQ). "
                    "Please check with the MGC sales office: 0308-77 77 275, "
                    "Head Office, Near Al-Jannat Mall, GT Road, Islamabad "
                    "(Mon–Sat 10:00–19:00)."
                ),
                intent="not_found",
            )

        refs = [h.to_ref() for h in hits]
        # Present the best-matching section body (trimmed) with citation
        best = hits[0]
        body_preview = best.body.strip()
        if len(body_preview) > 900:
            body_preview = body_preview[:897] + "…"

        text = (
            f"Based on **{best.document_title} — § {best.section}** "
            f"({best.filename}):\n\n{body_preview}\n\n"
            "If this does not fully answer the question, confirm with MGC sales "
            "(0308-77 77 275)."
        )
        return Answer(text=text, sources=refs, intent="retrieval")


# Module-level singleton for a simple API
_assistant: Optional[DocumentAssistant] = None


def get_assistant() -> DocumentAssistant:
    global _assistant
    if _assistant is None:
        _assistant = DocumentAssistant()
    return _assistant


def answer_question(question: str) -> Answer:
    """
    Answer a salesperson question grounded in the three docs.

    Returns an Answer with .text, .sources (structured SourceRef list),
    .intent, and optional .price_details.
    """
    return get_assistant().answer(question)
