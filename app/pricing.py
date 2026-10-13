"""
Deterministic pricing for MGC Aurora Heights.

Order of operations (explicit):
  1. Look up base price by block + unit type.
  2. Compute each location premium independently as a percentage of the BASE price.
  3. Sum premiums (cumulative / additive on base — not compounded on each other).
  4. Apply discounts ONLY to the base price (never to premiums or other charges).
  5. Final unit price = (base − discounts) + premiums.
  6. Booking / token = 10% of the final unit price (standard payment plan).

The "50% upfront" discount is a discount *condition* that unlocks 6% off base.
It is NOT the booking/token amount. Booking remains 10% unless MGC specifies otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional


# ---------------------------------------------------------------------------
# Source tables — from docs/02_price_list_payment_plan.md
# ---------------------------------------------------------------------------

BASE_PRICES: dict[tuple[str, str], Decimal] = {
    ("A", "Studio"): Decimal("8640000"),
    ("A", "1-Bed Standard"): Decimal("13320000"),
    ("A", "2-Bed Standard"): Decimal("21850000"),
    ("B", "1-Bed Standard"): Decimal("13680000"),
    ("B", "2-Bed Standard"): Decimal("22425000"),
    ("B", "2-Bed Corner"): Decimal("26855000"),
    ("B", "3-Bed Executive"): Decimal("39480000"),
    ("B", "4-Bed Penthouse"): Decimal("88400000"),
}

# Location premiums as fractions of base (docs/02 § Location Premiums)
FLOOR_PREMIUM_13_19 = Decimal("0.04")
FLOOR_PREMIUM_20_22 = Decimal("0.07")
CORNER_PREMIUM = Decimal("0.03")
MARGALLA_PREMIUM = Decimal("0.06")

# Discounts apply to base only (docs/02 § Discounts)
DISCOUNT_FULL_CASH = Decimal("0.12")
DISCOUNT_50_UPFRONT = Decimal("0.06")
DISCOUNT_OVERSEAS = Decimal("0.02")
DISCOUNT_SECOND_UNIT = Decimal("0.015")

BOOKING_SHARE = Decimal("0.10")  # docs/02 § Standard Payment Plan

# Unit types that cannot be Margalla-facing (docs/01 § Unit Configuration)
NO_MARGALLA_TYPES = frozenset({"Studio", "1-Bed Standard"})


class PricingError(ValueError):
    """Invalid or unsupported pricing combination."""


def _money(value: Decimal) -> Decimal:
    """Round to whole PKR (half up)."""
    return value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def lookup_base_price(block: str, unit_type: str) -> Decimal:
    """Return base list price for (block, unit_type)."""
    key = (block.strip().upper(), unit_type.strip())
    if key not in BASE_PRICES:
        raise PricingError(
            f"No base price for block {key[0]!r}, unit type {key[1]!r}. "
            "Available: "
            + ", ".join(f"{b}/{u}" for b, u in sorted(BASE_PRICES))
        )
    return BASE_PRICES[key]


def floor_premium_rate(floor: Optional[int]) -> Decimal:
    """Floor premium as a fraction of base, or 0 if none / not applicable."""
    if floor is None:
        return Decimal("0")
    if 13 <= floor <= 19:
        return FLOOR_PREMIUM_13_19
    if 20 <= floor <= 22:
        return FLOOR_PREMIUM_20_22
    if 1 <= floor <= 12 or floor == 0:
        return Decimal("0")
    raise PricingError(f"Unsupported floor number: {floor}")


def corner_premium_rate(is_corner: bool) -> Decimal:
    return CORNER_PREMIUM if is_corner else Decimal("0")


def margalla_premium_rate(is_margalla: bool) -> Decimal:
    return MARGALLA_PREMIUM if is_margalla else Decimal("0")


def validate_combination(
    block: str,
    unit_type: str,
    floor: Optional[int] = None,
    is_corner: bool = False,
    is_margalla: bool = False,
) -> None:
    """Reject combinations the documents say are unavailable."""
    block = block.strip().upper()
    unit_type = unit_type.strip()

    if (block, unit_type) not in BASE_PRICES:
        raise PricingError(f"Unknown unit: Block {block} {unit_type}")

    if unit_type == "4-Bed Penthouse":
        if block != "B":
            raise PricingError("4-Bed Penthouse is only in Block B.")
        if floor is not None and floor not in (20, 21, 22):
            raise PricingError("4-Bed Penthouse is only on floors 20–22.")

    if unit_type == "2-Bed Corner" and block != "B":
        raise PricingError("2-Bed Corner is only in Block B.")

    if unit_type == "3-Bed Executive" and block != "B":
        raise PricingError("3-Bed Executive is only in Block B.")

    if unit_type == "Studio" and block != "A":
        raise PricingError("Studio is only in Block A.")

    if is_margalla and unit_type in NO_MARGALLA_TYPES:
        raise PricingError(
            f"{unit_type} units are not available with a Margalla-facing orientation."
        )

    # Brochure: all units above floor 12 in Block B face Margalla — caller may
    # still set is_margalla explicitly; we only validate impossibility.


@dataclass
class PremiumBreakdown:
    floor_rate: Decimal = Decimal("0")
    corner_rate: Decimal = Decimal("0")
    margalla_rate: Decimal = Decimal("0")
    floor_amount: Decimal = Decimal("0")
    corner_amount: Decimal = Decimal("0")
    margalla_amount: Decimal = Decimal("0")

    @property
    def total_rate(self) -> Decimal:
        return self.floor_rate + self.corner_rate + self.margalla_rate

    @property
    def total_amount(self) -> Decimal:
        return self.floor_amount + self.corner_amount + self.margalla_amount


@dataclass
class DiscountBreakdown:
    upfront_50_rate: Decimal = Decimal("0")
    full_cash_rate: Decimal = Decimal("0")
    overseas_rate: Decimal = Decimal("0")
    second_unit_rate: Decimal = Decimal("0")
    upfront_50_amount: Decimal = Decimal("0")
    full_cash_amount: Decimal = Decimal("0")
    overseas_amount: Decimal = Decimal("0")
    second_unit_amount: Decimal = Decimal("0")

    @property
    def total_rate(self) -> Decimal:
        return (
            self.upfront_50_rate
            + self.full_cash_rate
            + self.overseas_rate
            + self.second_unit_rate
        )

    @property
    def total_amount(self) -> Decimal:
        return (
            self.upfront_50_amount
            + self.full_cash_amount
            + self.overseas_amount
            + self.second_unit_amount
        )


@dataclass
class PriceQuote:
    block: str
    unit_type: str
    base_price: Decimal
    premiums: PremiumBreakdown = field(default_factory=PremiumBreakdown)
    discounts: DiscountBreakdown = field(default_factory=DiscountBreakdown)
    price_after_discounts_on_base: Decimal = Decimal("0")
    final_price: Decimal = Decimal("0")
    booking_token: Decimal = Decimal("0")
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "block": self.block,
            "unit_type": self.unit_type,
            "base_price": str(self.base_price),
            "premium_total": str(self.premiums.total_amount),
            "premium_rate": str(self.premiums.total_rate),
            "discount_total": str(self.discounts.total_amount),
            "discount_rate_on_base": str(self.discounts.total_rate),
            "final_price": str(self.final_price),
            "booking_token": str(self.booking_token),
            "notes": list(self.notes),
        }


def calculate_price(
    block: str,
    unit_type: str,
    *,
    floor: Optional[int] = None,
    is_corner: bool = False,
    is_margalla: bool = False,
    discount_50_upfront: bool = False,
    discount_full_cash: bool = False,
    discount_overseas: bool = False,
    discount_second_unit: bool = False,
) -> PriceQuote:
    """
    Compute final unit price and booking/token with documented order of operations.

    Premiums: each rate × base, then summed (cumulative on base).
    Discounts: each rate × base only; never applied to premiums.
    Final = (base − discount_total) + premium_total.
    Booking/token = 10% × final.
    """
    block = block.strip().upper()
    unit_type = unit_type.strip()

    # 2-Bed Corner unit type already is a corner product; still allow explicit
    # corner premium when the caller (or docs example) stacks the corner premium.
    if unit_type == "2-Bed Corner":
        is_corner = True

    validate_combination(block, unit_type, floor, is_corner, is_margalla)

    if discount_50_upfront and discount_full_cash:
        raise PricingError(
            "Cannot combine full-cash (12%) and 50%-upfront (6%) discounts."
        )

    base = lookup_base_price(block, unit_type)

    premiums = PremiumBreakdown(
        floor_rate=floor_premium_rate(floor),
        corner_rate=corner_premium_rate(is_corner),
        margalla_rate=margalla_premium_rate(is_margalla),
    )
    premiums.floor_amount = _money(base * premiums.floor_rate)
    premiums.corner_amount = _money(base * premiums.corner_rate)
    premiums.margalla_amount = _money(base * premiums.margalla_rate)

    discounts = DiscountBreakdown()
    if discount_50_upfront:
        discounts.upfront_50_rate = DISCOUNT_50_UPFRONT
        discounts.upfront_50_amount = _money(base * DISCOUNT_50_UPFRONT)
    if discount_full_cash:
        discounts.full_cash_rate = DISCOUNT_FULL_CASH
        discounts.full_cash_amount = _money(base * DISCOUNT_FULL_CASH)
    if discount_overseas:
        discounts.overseas_rate = DISCOUNT_OVERSEAS
        discounts.overseas_amount = _money(base * DISCOUNT_OVERSEAS)
    if discount_second_unit:
        discounts.second_unit_rate = DISCOUNT_SECOND_UNIT
        discounts.second_unit_amount = _money(base * DISCOUNT_SECOND_UNIT)

    discounted_base = base - discounts.total_amount
    final_price = discounted_base + premiums.total_amount
    booking = _money(final_price * BOOKING_SHARE)

    notes: list[str] = []
    notes.append(
        "Order: base -> add location premiums (each % of base) -> "
        "subtract discounts (each % of base only) -> booking = 10% of final."
    )
    if discount_50_upfront:
        notes.append(
            "The 50% upfront option unlocks a 6% discount on the base price; "
            "it is not the booking/token amount. Booking/token remains 10% of "
            "the final unit price under the standard payment plan."
        )
    if premiums.total_amount and discounts.total_amount:
        notes.append("Location premiums are not discounted.")

    return PriceQuote(
        block=block,
        unit_type=unit_type,
        base_price=base,
        premiums=premiums,
        discounts=discounts,
        price_after_discounts_on_base=discounted_base,
        final_price=final_price,
        booking_token=booking,
        notes=notes,
    )


def format_pkr(amount: Decimal) -> str:
    """Format as PKR with thousands separators."""
    quantized = _money(amount)
    return f"PKR {quantized:,}"
