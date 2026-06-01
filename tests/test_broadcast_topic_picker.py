from __future__ import annotations

from datetime import date, datetime, timezone

from newsletter_pod.broadcast.models import BroadcastEpisodeRecord, BroadcastLoopRecord
from newsletter_pod.broadcast.repository import InMemoryBroadcastRepository
from newsletter_pod.broadcast.topic_picker import (
    BroadcastTopicPicker,
    TopicProposal,
    _normalize_hashtags,
)


class _FakeProposer:
    """Returns whatever was passed at construction time. `returns` can be
    a TopicProposal (the modern shape), a bare string (back-compat path),
    or None (proposer abstained)."""

    def __init__(self, *, returns=None) -> None:
        self.returns = returns
        self.calls: list[dict] = []

    def propose(self, *, audience_persona, prior_feedback_summary, seed_topics):
        self.calls.append({
            "audience_persona": audience_persona,
            "prior_feedback_summary": prior_feedback_summary,
            "seed_topics": list(seed_topics),
        })
        return self.returns


def _loop(seed_topics=None, persona="indie founders") -> BroadcastLoopRecord:
    return BroadcastLoopRecord(
        loop_id="us-morning",
        region="US",
        timezone="America/Los_Angeles",
        audience_persona=persona,
        seed_topics=seed_topics or [],
        created_at=datetime(2026, 5, 30, tzinfo=timezone.utc),
        updated_at=datetime(2026, 5, 30, tzinfo=timezone.utc),
    )


def _episode_with_feedback(repo, *, loop_id, summary, episode_id="aaaaaaaaaaaaaaaa", run_date=date(2026, 5, 30)):
    repo.save_episode(BroadcastEpisodeRecord(
        episode_id=episode_id,
        loop_id=loop_id,
        run_date=run_date,
        topic_used="yesterday's topic",
        title="t",
        show_notes="n",
        audio_object_name=f"broadcast/{episode_id}.mp3",
        video_object_name=f"broadcast/{episode_id}.mp4",
        feedback_summary=summary,
        created_at=datetime(2026, 5, 30, 1, tzinfo=timezone.utc),
    ))


def test_pick_uses_proposer_topic_when_available():
    repo = InMemoryBroadcastRepository()
    proposer = _FakeProposer(returns="What Anthropic shipped this week")
    picker = BroadcastTopicPicker(proposer=proposer, repository=repo)

    topic, brief = picker.pick(_loop(seed_topics=["fallback-1"]))

    assert topic == "What Anthropic shipped this week"
    assert brief.topic == "What Anthropic shipped this week"
    assert brief.audience_hint == "indie founders"


def test_pick_passes_prior_feedback_to_proposer():
    repo = InMemoryBroadcastRepository()
    _episode_with_feedback(repo, loop_id="us-morning", summary="people want more on tool use")
    proposer = _FakeProposer(returns="Tool-use deep dive")
    picker = BroadcastTopicPicker(proposer=proposer, repository=repo)

    topic, brief = picker.pick(_loop())

    assert proposer.calls[0]["prior_feedback_summary"] == "people want more on tool use"
    assert brief.prior_feedback_summary == "people want more on tool use"
    assert topic == "Tool-use deep dive"


def test_pick_falls_back_to_round_robin_seed_when_proposer_returns_none():
    repo = InMemoryBroadcastRepository()
    proposer = _FakeProposer(returns=None)
    picker = BroadcastTopicPicker(proposer=proposer, repository=repo)
    loop = _loop(seed_topics=["seed-a", "seed-b", "seed-c"])

    # No episodes yet → index 0
    topic, _ = picker.pick(loop)
    assert topic == "seed-a"

    # After one episode → index 1
    _episode_with_feedback(repo, loop_id="us-morning", summary=None, episode_id="bbbbbbbbbbbbbbbb", run_date=date(2026, 5, 31))
    topic, _ = picker.pick(loop)
    assert topic == "seed-b"


def test_pick_falls_back_to_persona_when_no_proposer_or_seeds():
    repo = InMemoryBroadcastRepository()
    picker = BroadcastTopicPicker(proposer=None, repository=repo)

    topic, _ = picker.pick(_loop(persona="ML engineers", seed_topics=[]))

    assert topic == "ML engineers"


def test_pick_proposer_none_skips_llm_step():
    repo = InMemoryBroadcastRepository()
    picker = BroadcastTopicPicker(proposer=None, repository=repo)

    topic, _ = picker.pick(_loop(seed_topics=["a"]))

    assert topic == "a"


def test_pick_surfaces_topic_hashtags_from_proposal():
    repo = InMemoryBroadcastRepository()
    proposer = _FakeProposer(
        returns=TopicProposal(
            topic="OpenAI's enterprise pivot mirrors Salesforce",
            hashtags=["#OpenAI", "#Salesforce"],
        )
    )
    picker = BroadcastTopicPicker(proposer=proposer, repository=repo)

    topic, brief = picker.pick(_loop())

    assert topic == "OpenAI's enterprise pivot mirrors Salesforce"
    assert brief.topic_hashtags == ["#OpenAI", "#Salesforce"]


def test_pick_returns_empty_hashtags_when_proposer_returns_bare_string():
    # Backward-compat path: older proposers returning a plain string
    # still produce a usable topic, with no entity hashtags.
    repo = InMemoryBroadcastRepository()
    proposer = _FakeProposer(returns="The compute bottleneck")
    picker = BroadcastTopicPicker(proposer=proposer, repository=repo)

    topic, brief = picker.pick(_loop())

    assert topic == "The compute bottleneck"
    assert brief.topic_hashtags == []


def test_pick_returns_empty_hashtags_for_seed_or_persona_fallback():
    # Seed-topic and persona fallbacks don't have an LLM step to derive
    # hashtags from, so the brief gets [] and the tweet ends up with
    # only the brand-static set.
    repo = InMemoryBroadcastRepository()
    proposer = _FakeProposer(returns=None)
    picker = BroadcastTopicPicker(proposer=proposer, repository=repo)

    _, brief = picker.pick(_loop(seed_topics=["a"]))
    assert brief.topic_hashtags == []

    picker2 = BroadcastTopicPicker(proposer=None, repository=repo)
    _, brief2 = picker2.pick(_loop(persona="X", seed_topics=[]))
    assert brief2.topic_hashtags == []


def test_normalize_hashtags_cleans_llm_output():
    assert _normalize_hashtags(["#OpenAI", "Salesforce"]) == ["#OpenAI", "#Salesforce"]
    # Strips junk characters, keeps the alphanumeric body.
    assert _normalize_hashtags(["#Sam Altman", " #GPT-5 "]) == ["#Sam", "#GPT"]
    # Dedupes case-insensitively, caps at 3.
    assert _normalize_hashtags(["#AI", "#ai", "#Tech", "#X", "#Y"]) == ["#AI", "#Tech", "#X"]
    # Bad inputs become an empty list, not an exception.
    assert _normalize_hashtags(None) == []
    assert _normalize_hashtags("not a list") == []
    assert _normalize_hashtags([1, {"x": 1}, ""]) == []
