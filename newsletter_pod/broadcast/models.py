from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class BroadcastLoopRecord(BaseModel):
    """Per-loop config: one row drives one daily slot on one region/audience.

    Multi-loop is the cheap axis — adding a new region is a row insert
    plus one Cloud Scheduler entry; the generation/publish code is
    loop-agnostic. `seed_topics` exists for cold-start runs (and as a
    fallback when LLM topic-picking fails); under normal operation the
    LLM picker reads the prior episode's `feedback_summary`.

    `post_local_time` is "HH:MM" 24h; `timezone` is an IANA name
    ("America/Los_Angeles"). Cron expressions are derived from these
    rather than stored, so updating the slot time is just a write +
    re-running schedule_broadcast_loop.sh.
    """

    loop_id: str
    region: str
    timezone: str
    audience_persona: str
    post_local_time: str = "08:00"
    seed_topics: list[str] = Field(default_factory=list)
    active: bool = True
    # Default copy posted under the episode tweet to solicit feedback;
    # set to empty string on the loop to suppress entirely.
    feedback_prompt_text: Optional[str] = None
    # Curated source ids (matching newsletter_pod source_id values) the
    # broadcast pipeline should read recent items from when assembling
    # the brief. Empty list means "no grounding" — the LLM riffs on the
    # topic alone (Phase 0 behavior). Lookback window and per-source
    # item caps are applied at fetch time, not stored here.
    source_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class BroadcastEpisodeRecord(BaseModel):
    """One persisted broadcast episode. Created when the scheduled run
    fires; updated when the operator pastes feedback.

    `feedback_summary` is the LLM-condensed read of the replies the
    operator pasted in. Tomorrow's run for the same loop reads this
    when picking the next topic.

    Stays decoupled from the asset URLs — the GCS object names are
    derived from the episode_id, same as Phase 0.
    """

    episode_id: str
    loop_id: str
    run_date: date
    topic_used: str
    title: str
    show_notes: str
    audio_object_name: str
    video_object_name: str
    episode_tweet_id: Optional[str] = None
    episode_tweet_url: Optional[str] = None
    feedback_prompt_tweet_id: Optional[str] = None
    feedback_prompt_tweet_url: Optional[str] = None
    feedback_summary: Optional[str] = None
    feedback_raw: Optional[str] = None
    feedback_pasted_at: Optional[datetime] = None
    created_at: datetime
