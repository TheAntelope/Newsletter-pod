from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class BroadcastBrief:
    """Inputs to a single broadcast episode.

    `topic` is the only required field. The others tune voice and let the
    daily-loop feedback step (later phase) thread prior-day signal into
    tomorrow's brief without us having to change call sites.
    """

    topic: str
    audience_hint: Optional[str] = None
    prior_feedback_summary: Optional[str] = None
    desired_minutes: int = 5


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

    sections += [
        "",
        "Structure guidance:",
        "- Open with the hook before introducing the hosts.",
        "- One central thesis the hosts develop together — not a list of bullet points.",
        "- The secondary host pushes back at least once; this isn't a fluff piece.",
        "- Close with a single forward-looking question or call-to-action the audience "
        "can reply to.",
    ]

    return "\n".join(sections)
