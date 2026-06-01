from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..models import SourceItem


@dataclass(frozen=True)
class BroadcastBrief:
    """Inputs to a single broadcast episode.

    `topic` is the only required field. The others tune voice and let the
    daily-loop feedback step (later phase) thread prior-day signal into
    tomorrow's brief without us having to change call sites.

    `source_items` grounds the LLM in actual recent newsletter/RSS items
    from the loop's curated source list. Empty list keeps the Phase-0
    behavior (pure single-topic riff).
    """

    topic: str
    audience_hint: Optional[str] = None
    prior_feedback_summary: Optional[str] = None
    desired_minutes: int = 5
    source_items: list[SourceItem] = field(default_factory=list)
    # LLM-derived entity hashtags for this episode (e.g. ["#OpenAI",
    # "#Salesforce"]). Combined with the runner's brand-static set
    # (DEFAULT_TWEET_HASHTAGS) when building the tweet so each post
    # carries hashtags that actually match the day's story.
    topic_hashtags: list[str] = field(default_factory=list)


# Cap how many items per source we surface to the LLM. Same source spamming
# the brief crowds out alternative angles; a small per-source budget keeps
# diversity even when one feed has 30 fresh items.
_MAX_ITEMS_PER_SOURCE_IN_BRIEF = 4
# Hard ceiling across the whole brief. Beyond this the prompt becomes a
# wall of text and the LLM picks ~3-5 anyway.
_MAX_TOTAL_ITEMS_IN_BRIEF = 18
# Per-summary char budget. Newsletter summaries are often two-three
# sentences already; long ones get truncated mid-sentence to keep the
# total prompt size sensible.
_MAX_SUMMARY_CHARS = 320


def build_broadcast_prompt(brief: BroadcastBrief) -> str:
    """Format a topic brief as 'source material' the existing podcast LLM
    chain can chew on.

    The existing `PodcastApiClient.generate()` pipeline takes a free-form
    prompt and a UX config, then runs the two-host script + TTS path.
    We reuse it as-is and shape the prompt around a single topic instead
    of an RSS digest.
    """
    topic = brief.topic.strip()
    if not topic:
        raise ValueError("BroadcastBrief.topic is required")

    sections: list[str] = [
        "BROADCAST EPISODE — single-topic deep dive (not a daily news digest).",
        "Distribution: posted to X as a short video clip. Optimize for an X audience: "
        "punchy framing, a strong cold open in the first 10 seconds, one quotable line "
        "per host that would survive being clipped on its own.",
        f"Target runtime: roughly {brief.desired_minutes} minutes.",
        "",
        "Topic:",
        topic,
    ]

    if brief.audience_hint:
        sections += [
            "",
            "Audience hint:",
            brief.audience_hint.strip(),
        ]

    if brief.prior_feedback_summary:
        sections += [
            "",
            "Signal from yesterday's audience (use as a steer, not a script):",
            brief.prior_feedback_summary.strip(),
        ]

    source_block = _format_source_items_block(brief.source_items)
    if source_block:
        sections += ["", source_block]

    sections += [
        "",
        "Structure guidance:",
        "- Open with the hook before introducing the hosts.",
        "- One central thesis the hosts develop together — not a list of bullet points.",
        "- The secondary host pushes back at least once; this isn't a fluff piece.",
        "- Close with a single forward-looking question or call-to-action the audience "
        "can reply to.",
    ]

    if brief.source_items:
        sections += [
            "- Ground every concrete claim in one of the source items above; cite the "
            "publication name out loud at least once when you do. Do not invent stats "
            "or quotes the sources do not contain.",
        ]

    return "\n".join(sections)


def _format_source_items_block(items: list[SourceItem]) -> str:
    if not items:
        return ""

    # Newest first, then cap per source so one prolific feed can't crowd
    # out everything else, then a global ceiling.
    sorted_items = sorted(items, key=lambda it: it.published_at, reverse=True)
    per_source: dict[str, int] = {}
    kept: list[SourceItem] = []
    for item in sorted_items:
        count = per_source.get(item.source_id, 0)
        if count >= _MAX_ITEMS_PER_SOURCE_IN_BRIEF:
            continue
        per_source[item.source_id] = count + 1
        kept.append(item)
        if len(kept) >= _MAX_TOTAL_ITEMS_IN_BRIEF:
            break

    if not kept:
        return ""

    lines = [
        "Recent source items (use these as grounding for specific facts, dates, "
        "and quoted positions — prefer them over training-data memory):",
    ]
    for item in kept:
        published = item.published_at.date().isoformat()
        summary = (item.summary or "").strip()
        if len(summary) > _MAX_SUMMARY_CHARS:
            summary = summary[: _MAX_SUMMARY_CHARS].rsplit(" ", 1)[0] + "…"
        title = item.title.strip()
        lines.append(
            f"- [{published}] {item.source_name} — {title}\n    {summary}"
        )
    return "\n".join(lines)
