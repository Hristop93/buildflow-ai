"""Tier-based access control for project sections (SPEC 6).

The backend always computes everything; this is where the server decides which
sections a project's purchased tier is allowed to read. Tier is per-project.
"""
from __future__ import annotations

# Ordered access levels — a tier can read its own level and everything below.
TIER_RANK = {"free": 0, "standard": 1, "pro": 2, "dd": 3}

# Minimum tier required to read each section (SPEC 5.2 / 6).
SECTION_TIERS = {
    "summary": "free",
    "route": "standard",
    "fees": "standard",
    "schedule": "pro",
    "economics": "pro",
    "journal": "pro",
    "risk": "dd",
    "export": "dd",
}

# Sections that actually have data in this phase. risk (Monte Carlo) and export
# (xlsx/pdf) are defined above for gating but land in later phases (SPEC 9).
IMPLEMENTED_SECTIONS = {"summary", "route", "fees", "schedule", "economics", "journal"}


def is_known_section(name: str) -> bool:
    return name in SECTION_TIERS


def required_tier(name: str) -> str:
    return SECTION_TIERS[name]


def can_access(project_tier: str, name: str) -> bool:
    have = TIER_RANK.get(project_tier, -1)
    need = TIER_RANK[SECTION_TIERS[name]]
    return have >= need
