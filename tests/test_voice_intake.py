from __future__ import annotations

from newsletter_pod.voice_intake import ExtractedIntake, _coerce_extracted


def test_coerce_extracted_handles_well_formed_payload():
    result = _coerce_extracted(
        {
            "topics": ["AI compute", "Premier League"],
            "named_entities": ["Anthropic", "Stratechery"],
            "anchor_phrases": ["chasing the compute story"],
            "vibe_notes": "Casual and quick.",
        }
    )
    assert isinstance(result, ExtractedIntake)
    assert result.topics == ["AI compute", "Premier League"]
    assert result.named_entities == ["Anthropic", "Stratechery"]
    assert result.anchor_phrases == ["chasing the compute story"]
    assert result.vibe_notes == "Casual and quick."


def test_coerce_extracted_drops_non_string_entries():
    result = _coerce_extracted(
        {
            "topics": ["valid", 42, None, ""],
            "named_entities": [{"nope": True}, "Anthropic"],
            "anchor_phrases": [],
            "vibe_notes": "",
        }
    )
    assert result.topics == ["valid"]
    assert result.named_entities == ["Anthropic"]
    assert result.anchor_phrases == []
    assert result.vibe_notes is None


def test_coerce_extracted_caps_list_sizes():
    result = _coerce_extracted(
        {
            "topics": [f"t{i}" for i in range(20)],
            "named_entities": [f"e{i}" for i in range(20)],
            "anchor_phrases": [f"p{i}" for i in range(20)],
        }
    )
    assert len(result.topics) == 8
    assert len(result.named_entities) == 8
    assert len(result.anchor_phrases) == 6


def test_coerce_extracted_deduplicates_case_insensitively():
    result = _coerce_extracted(
        {
            "topics": ["AI", "ai", "AI ", "Premier League"],
        }
    )
    assert result.topics == ["AI", "Premier League"]


def test_coerce_extracted_treats_null_vibe_strings_as_none():
    for value in ("", "null", "None", "n/a", "  "):
        result = _coerce_extracted({"vibe_notes": value})
        assert result.vibe_notes is None


def test_coerce_extracted_truncates_long_strings():
    long_topic = "x" * 200
    result = _coerce_extracted({"topics": [long_topic]})
    assert len(result.topics) == 1
    assert result.topics[0].endswith("…")
    assert len(result.topics[0]) <= 61  # 60 chars + ellipsis


def test_extracted_intake_is_empty_when_all_fields_blank():
    assert ExtractedIntake().is_empty()
    assert not ExtractedIntake(topics=["x"]).is_empty()
    assert not ExtractedIntake(vibe_notes="x").is_empty()
