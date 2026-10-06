"""Canonical commercial assumptions for deterministic demo data."""

CANONICAL_REVENUE_PER_CASE = 6.25


def revenue_for_cases(cases: int | float) -> float:
    return round(float(cases) * CANONICAL_REVENUE_PER_CASE, 2)
