from __future__ import annotations

from newsletter_pod.regions import region_for_timezone, source_region_matches


def test_region_for_timezone_maps_known_zones():
    assert region_for_timezone("Europe/Copenhagen") == "DK"
    assert region_for_timezone("America/New_York") == "US"
    assert region_for_timezone("Europe/London") == "GB"


def test_region_for_timezone_unmapped_or_blank_is_none():
    assert region_for_timezone("Asia/Tokyo") is None
    assert region_for_timezone("") is None
    assert region_for_timezone(None) is None


def test_source_region_matches_exact_country():
    assert source_region_matches("DK", "DK") is True
    assert source_region_matches("US", "GB") is False


def test_european_user_matches_pan_eu_sources():
    assert source_region_matches("DK", "EU") is True
    assert source_region_matches("FR", "EU") is True
    # Non-EU users do not match EU-wide sources.
    assert source_region_matches("US", "EU") is False


def test_region_neutral_source_never_matches():
    # A globally-relevant source (region None) is never "preferred".
    assert source_region_matches("DK", None) is False
    assert source_region_matches(None, "DK") is False
