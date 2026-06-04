"""Lightweight timezone → region resolution for regional content bias.

We don't ask users for their location; we derive a coarse region from the IANA
timezone already captured at signup (e.g. ``Europe/Copenhagen`` → ``DK``) and use
it to nudge region-matching news/politics sources up the onboarding swipe deck.

This is deliberately a small, hand-maintained table covering the regions our
catalog actually has sources for. An unmapped timezone returns ``None`` and the
deck simply isn't biased — never an error.
"""

from __future__ import annotations

from typing import Optional

# EU/EEA member-state country codes, used so European users also match pan-
# European ("EU") sources like Euronews and POLITICO Europe.
EU_EEA = frozenset(
    {
        "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR",
        "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK",
        "SI", "ES", "SE", "IS", "LI", "NO",
    }
)

# IANA timezone → ISO 3166-1 alpha-2 country code. Covers the countries our
# regional sources serve plus the common US zones; extend as the catalog grows.
_TZ_TO_REGION = {
    # Nordics
    "Europe/Copenhagen": "DK",
    "Europe/Stockholm": "SE",
    "Europe/Oslo": "NO",
    "Europe/Helsinki": "FI",
    "Atlantic/Reykjavik": "IS",
    # Western/Central Europe
    "Europe/London": "GB",
    "Europe/Dublin": "IE",
    "Europe/Berlin": "DE",
    "Europe/Paris": "FR",
    "Europe/Rome": "IT",
    "Europe/Amsterdam": "NL",
    "Europe/Brussels": "BE",
    "Europe/Madrid": "ES",
    "Europe/Lisbon": "PT",
    "Europe/Vienna": "AT",
    "Europe/Zurich": "CH",
    "Europe/Warsaw": "PL",
    # United States (and territories that read US national news)
    "America/New_York": "US",
    "America/Detroit": "US",
    "America/Chicago": "US",
    "America/Denver": "US",
    "America/Phoenix": "US",
    "America/Los_Angeles": "US",
    "America/Anchorage": "US",
    "Pacific/Honolulu": "US",
}


def region_for_timezone(timezone: Optional[str]) -> Optional[str]:
    """Resolve an IANA timezone to a region code, or None if unmapped."""
    if not timezone:
        return None
    return _TZ_TO_REGION.get(timezone.strip())


def source_region_matches(user_region: Optional[str], source_region: Optional[str]) -> bool:
    """True when a source's region is relevant to the user's region.

    Exact country match, plus European users matching pan-EU ("EU") sources.
    Region-neutral sources (``source_region`` None) never "match" — they're
    globally eligible and simply aren't boosted.
    """
    if not user_region or not source_region:
        return False
    if user_region == source_region:
        return True
    if source_region == "EU" and user_region in EU_EEA:
        return True
    return False
