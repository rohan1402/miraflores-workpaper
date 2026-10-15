"""Work areas (D3): the parts of the return that own documents and get signed.

Preparer and reviewer sign each area. California is a lens, not an area: each
California line belongs to the area that owns the same income or deduction,
so a California change reopens that area. Lines that only total or compute
tax belong to the return itself, which the partner signs once.
"""

from __future__ import annotations

# Ids match firm.budget_hours where the firm budgets the area.
SIGNED_AREAS: dict[str, str] = {
    "wages_and_stock_compensation": "Wages and stock compensation",
    "investments_and_digital_assets": "Investments and digital assets",
    "business": "Business",
    "rentals_and_sale": "Rentals and the sale",
    "pass_throughs_and_basis": "Passthroughs and basis",
    "deductions_and_credits": "Deductions and credits",
    "payments": "Payments",
}

RETURN = "return"  # summary and tax computation lines; covered by the partner release

# Lines computed from the whole return (AMT, NIIT, QBI limit, credits that phase out
# with AGI, penalties, amount owed). They move whenever anything moves, so they belong
# to the partner's signature on the return, not to an area. Otherwise a late K-1 would
# reopen the wages sign-off through AMT (D3 says it must not).
_RETURN_LEVEL: tuple[str, ...] = (
    "F6251.", "Sch2.1", "Sch2.11", "Sch2.12", "F8959.", "F8960.", "F540NR.61",
    "F8995", "F1040.13", "F1040.19", "F8812.", "F8863.", "F540NR.39",
    "F1040.37", "F1040.38", "F540NR.97", "F2210.", "FTB5805.",
    "SchE.41", "SchCA540NR.17.",
)

# First match wins, so specific prefixes come before general ones.
_LINE_AREA_RULES: list[tuple[str, str]] = [
    # Wages and stock compensation
    ("F1040.1", "wages_and_stock_compensation"),
    ("SchCA540NR.1.", "wages_and_stock_compensation"),
    # Investments and digital assets
    ("F1040.2", "investments_and_digital_assets"),
    ("F1040.3", "investments_and_digital_assets"),
    ("F1040.7", "investments_and_digital_assets"),
    ("SchB.", "investments_and_digital_assets"),
    ("SchD.", "investments_and_digital_assets"),
    ("F8949.", "investments_and_digital_assets"),
    ("F8938.", "investments_and_digital_assets"),
    ("Sch3.1", "investments_and_digital_assets"),
    ("SchCA540NR.2.", "investments_and_digital_assets"),
    ("SchCA540NR.3.", "investments_and_digital_assets"),
    ("SchCA540NR.7.", "investments_and_digital_assets"),
    # Business
    ("SchC.", "business"),
    ("SchSE.", "business"),
    ("F4562-C.", "business"),
    ("Sch1.3", "business"),
    ("Sch1.15", "business"),
    ("Sch1.16", "business"),
    ("Sch1.17", "business"),
    ("Sch2.4", "business"),
    ("SchCA540NR.12.", "business"),
    ("SchCA540NR.26.", "business"),
    ("FTB3885A.STU-", "business"),
    # Passthroughs and basis (K-1s, S corp basis, IRA basis)
    ("SchE.28", "pass_throughs_and_basis"),
    ("SchE.32", "pass_throughs_and_basis"),
    ("F7203.", "pass_throughs_and_basis"),
    ("F8606.", "pass_throughs_and_basis"),
    ("F1040.4", "pass_throughs_and_basis"),
    ("SchCA540NR.4.", "pass_throughs_and_basis"),
    ("ScheduleS.", "pass_throughs_and_basis"),
    # Rentals and the sale
    ("SchE.", "rentals_and_sale"),
    ("F4562-E.", "rentals_and_sale"),
    ("F4797.", "rentals_and_sale"),
    ("F8582.", "rentals_and_sale"),
    ("FTB3885A.SAC-", "rentals_and_sale"),
    # Deductions and credits
    ("SchA.", "deductions_and_credits"),
    ("SchCA540NR.A.", "deductions_and_credits"),
    ("F8283.", "deductions_and_credits"),
    ("F2441.", "deductions_and_credits"),
    ("F8889.", "deductions_and_credits"),
    ("F8867.", "deductions_and_credits"),
    ("Sch1.13", "deductions_and_credits"),
    ("F1040.12", "deductions_and_credits"),
    # Payments
    ("F1040.25", "payments"),
    ("F1040.26", "payments"),
    ("F1040.31", "payments"),
    ("F1040.33", "payments"),
    ("Sch3.10", "payments"),
    ("Sch3.11", "payments"),
    ("Sch3.15", "payments"),
    ("F540NR.71", "payments"),
    ("F540NR.72", "payments"),
    ("F540NR.73", "payments"),
    ("F540NR.78", "payments"),
]


def area_of_line(key: str) -> str:
    """Which work area owns a return line. Totals and tax computation belong to the return."""
    if any(_matches(key, prefix) for prefix in _RETURN_LEVEL):
        return RETURN
    for prefix, area in _LINE_AREA_RULES:
        if _matches(key, prefix):
            return area
    return RETURN


def _matches(key: str, prefix: str) -> bool:
    """Prefix match that respects line numbers: 'F1040.1' matches F1040.1a but not F1040.10."""
    if not key.startswith(prefix):
        return False
    rest = key[len(prefix):]
    return not (prefix[-1].isdigit() and rest[:1].isdigit())


def lines_in_area(lines: dict[str, dict], area: str) -> list[str]:
    return sorted(key for key in lines if area_of_line(key) == area)
