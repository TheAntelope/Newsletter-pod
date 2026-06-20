from __future__ import annotations

from datetime import date, datetime, timezone

from newsletter_pod.broadcast.models import BroadcastEpisodeRecord, BroadcastLoopRecord
from newsletter_pod.broadcast.repository import InMemoryBroadcastRepository
from newsletter_pod.broadcast.topic_picker import BroadcastTopicPicker, TopicProposal
from newsletter_pod.models import SourceItem


class _FakeProposer:
    def __init__(self, *, returns: str | None = None) -> None:
        self.returns = returns
        self.calls: list[dict] = []

    def propose(self, *, audience_persona, prior_feedback_summary, seed_topics):
        self.calls.append({
            "audience_persona": audience_persona,
            "prior_feedback_summary": prior_feedback_summary,
            "seed_topics": list(seed_topics),
        })
        return self.returns


def _loop(seed_topics=None, persona="indie founders", desired_minutes=None) -> BroadcastLoopRecord:
    return BroadcastLoopRecord(
        loop_id="us-morning",
        region="US",
        timezone="America/Los_Angeles",
        audience_persona=persona,
        seed_topics=seed_topics or [],
        desired_minutes=desired_minutes,
        created_at=datetime(2026, 5, 30, tzinfo=timezone.utc),
        updated_at=datetime(2026, 5, 30, tzinfo=timezone.utc),
    )


def test_pick_defaults_to_one_minute_when_loop_has_no_length():
    repo = InMemoryBroadcastRepository()
    proposer = _FakeProposer(returns="A topic")
    picker = BroadcastTopicPicker(proposer=proposer, repository=repo)

    _topic, brief = picker.pick(_loop())

    # Default short-clip length preserved for X loops (2-min video cap).
    assert brief.desired_minutes == 1


def test_pick_honours_per_loop_desired_minutes():
    repo = InMemoryBroadcastRepository()
    proposer = _FakeProposer(returns="A topic")
    picker = BroadcastTopicPicker(proposer=proposer, repository=repo)

    _topic, brief = picker.pick(_loop(desired_minutes=5))

    # A feed-only loop (e.g. the website daily show) can run longer.
    assert brief.desired_minutes == 5


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


# --- Source-led selection (no feedback yet) ---------------------------------


class _FakeSourceProposer:
    """Proposer that supports both the feedback path and source-led selection.
    `source_proposal` is what propose_from_sources returns."""

    def __init__(self, *, returns: str | None = None, source_proposal: TopicProposal | None = None) -> None:
        self.returns = returns
        self.source_proposal = source_proposal
        self.propose_calls: list[dict] = []
        self.source_calls: list[dict] = []

    def propose(self, *, audience_persona, prior_feedback_summary, seed_topics):
        self.propose_calls.append({
            "prior_feedback_summary": prior_feedback_summary,
            "seed_topics": list(seed_topics),
        })
        return self.returns

    def propose_from_sources(self, *, audience_persona, source_items):
        self.source_calls.append({
            "audience_persona": audience_persona,
            "source_items": list(source_items),
        })
        return self.source_proposal


def _src_item(title: str, *, source_id: str = "src-a") -> SourceItem:
    return SourceItem(
        source_id=source_id,
        source_name=f"name-{source_id}",
        guid=title,
        link=f"https://x.test/{title}",
        title=title,
        summary=f"summary for {title}",
        published_at=datetime(2026, 5, 30, tzinfo=timezone.utc),
        dedupe_key=title,
    )


def test_pick_no_feedback_uses_source_led_topic_and_narrows_grounding():
    repo = InMemoryBroadcastRepository()
    items = [_src_item("Story A"), _src_item("Story B"), _src_item("Story C")]
    proposer = _FakeSourceProposer(
        source_proposal=TopicProposal(topic="Story B, in depth", source_dedupe_key="Story B"),
    )
    picker = BroadcastTopicPicker(proposer=proposer, repository=repo)

    topic, brief = picker.pick(_loop(seed_topics=["seed-x"]), source_items=items)

    # Topic came from the sources, not the seed list...
    assert topic == "Story B, in depth"
    assert proposer.source_calls and proposer.source_calls[0]["source_items"] == items
    # ...and the episode is grounded on just the chosen story.
    assert [i.title for i in brief.source_items] == ["Story B"]
    # The seed-topic proposer path is not used when sources produced a topic.
    assert proposer.propose_calls == []


def test_pick_source_led_topic_without_pin_keeps_broad_grounding():
    repo = InMemoryBroadcastRepository()
    items = [_src_item("Story A"), _src_item("Story B")]
    proposer = _FakeSourceProposer(
        source_proposal=TopicProposal(topic="An angle", source_dedupe_key=None),
    )
    picker = BroadcastTopicPicker(proposer=proposer, repository=repo)

    topic, brief = picker.pick(_loop(), source_items=items)

    assert topic == "An angle"
    # No specific item pinned → ground on all recent items.
    assert [i.title for i in brief.source_items] == ["Story A", "Story B"]


def test_pick_no_feedback_falls_back_to_seed_proposer_when_no_source_topic():
    repo = InMemoryBroadcastRepository()
    items = [_src_item("Story A")]
    # Source selection declines (returns None); seed proposer still answers.
    proposer = _FakeSourceProposer(returns="Seed-based topic", source_proposal=None)
    picker = BroadcastTopicPicker(proposer=proposer, repository=repo)

    topic, brief = picker.pick(_loop(seed_topics=["seed-x"]), source_items=items)

    assert topic == "Seed-based topic"
    assert proposer.propose_calls[0]["prior_feedback_summary"] is None
    # Falls back to broad grounding on the available items.
    assert [i.title for i in brief.source_items] == ["Story A"]


def test_pick_with_feedback_ignores_source_led_selection():
    repo = InMemoryBroadcastRepository()
    _episode_with_feedback(repo, loop_id="us-morning", summary="more on pricing")
    items = [_src_item("Story A"), _src_item("Story B")]
    proposer = _FakeSourceProposer(
        returns="Pricing deep dive",
        source_proposal=TopicProposal(topic="Story A", source_dedupe_key="Story A"),
    )
    picker = BroadcastTopicPicker(proposer=proposer, repository=repo)

    topic, brief = picker.pick(_loop(), source_items=items)

    # Feedback wins; source-led selection is not consulted.
    assert topic == "Pricing deep dive"
    assert proposer.source_calls == []
    # Grounding stays broad in the feedback case.
    assert [i.title for i in brief.source_items] == ["Story A", "Story B"]
