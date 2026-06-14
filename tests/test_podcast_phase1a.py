"""Phase 1a: podcasts as a first-class source type.

Covers the show-notes path end to end without network: RSS enclosure + duration
extraction, podcast-flavoured prompt attribution, persistence round-trip of the
new fields, and a guard that the shipped catalog actually carries podcasts.
"""
from __future__ import annotations

from datetime import datetime, timezone

import feedparser

from newsletter_pod.candidate_queue import CandidateQueueService
from newsletter_pod.config import load_sources
from newsletter_pod.ingestion import (
    IngestionResult,
    RSSIngestionService,
    _audio_enclosure_url,
    _parse_itunes_duration,
)
from newsletter_pod.models import (
    PodcastUxConfig,
    SourceDefinition,
    SourceItem,
    SourceItemRecord,
)
from newsletter_pod.prompting import build_digest_prompt
from newsletter_pod.source_persistence import SourceItemPersistenceService
from newsletter_pod.user_models import UserSourceRecord
from newsletter_pod.user_repository import InMemoryControlPlaneRepository
from newsletter_pod.utils import utc_now

PODCAST_RSS = """<?xml version="1.0"?>
<rss version="2.0"
     xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
     xmlns:podcast="https://podcastindex.org/namespace/1.0">
  <channel>
    <title>Test Pod</title>
    <item>
      <title>Episode One</title>
      <link>https://pod.example/ep1?token=secret123</link>
      <guid>ep-1</guid>
      <pubDate>Tue, 10 Jun 2026 10:00:00 GMT</pubDate>
      <description>Show notes for episode one.</description>
      <itunes:duration>1:25:15</itunes:duration>
      <enclosure url="https://cdn.example/ep1.mp3?t=trackingid"
                 length="42" type="audio/mpeg"/>
    </item>
    <item>
      <title>Episode Two</title>
      <link>https://pod.example/ep2</link>
      <guid>ep-2</guid>
      <pubDate>Wed, 11 Jun 2026 10:00:00 GMT</pubDate>
      <description>Show notes for episode two.</description>
      <itunes:duration>600</itunes:duration>
      <enclosure url="https://cdn.example/ep2.mp3" length="42" type="audio/mpeg"/>
    </item>
  </channel>
</rss>"""

ARTICLE_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Blog</title>
  <item>
    <title>A Post</title>
    <link>https://blog.example/post</link>
    <guid>post-1</guid>
    <pubDate>Tue, 10 Jun 2026 10:00:00 GMT</pubDate>
    <description>Just a text post.</description>
  </item>
</channel></rss>"""


# --- _parse_itunes_duration ------------------------------------------------

def test_parse_duration_bare_seconds():
    assert _parse_itunes_duration("1515") == 1515


def test_parse_duration_clock_forms():
    assert _parse_itunes_duration("25:15") == 25 * 60 + 15
    assert _parse_itunes_duration("1:25:15") == 3600 + 25 * 60 + 15


def test_parse_duration_garbage_is_none():
    assert _parse_itunes_duration(None) is None
    assert _parse_itunes_duration("") is None
    assert _parse_itunes_duration("  ") is None
    assert _parse_itunes_duration("forty minutes") is None


def test_parse_duration_rejects_negative():
    assert _parse_itunes_duration("-5") is None
    assert _parse_itunes_duration("-1:30") is None
    assert _parse_itunes_duration("0") == 0


# --- _audio_enclosure_url --------------------------------------------------

def test_audio_enclosure_picks_audio_type():
    entry = feedparser.parse(PODCAST_RSS).entries[0]
    assert _audio_enclosure_url(entry) == "https://cdn.example/ep1.mp3?t=trackingid"


def test_audio_enclosure_none_without_enclosure():
    entry = feedparser.parse(ARTICLE_RSS).entries[0]
    assert _audio_enclosure_url(entry) is None


def test_audio_enclosure_skips_non_audio_before_audio():
    # A feed that attaches an image/chapters enclosure before the audio one must
    # still yield the audio href, not the image.
    entry = {
        "enclosures": [
            {"type": "image/jpeg", "href": "https://x.example/cover.jpg"},
            {"type": "audio/mpeg", "href": "https://x.example/ep.mp3"},
        ]
    }
    assert _audio_enclosure_url(entry) == "https://x.example/ep.mp3"


def test_audio_enclosure_none_when_only_non_audio():
    entry = {"enclosures": [{"type": "image/jpeg", "href": "https://x.example/c.jpg"}]}
    assert _audio_enclosure_url(entry) is None


def test_audio_enclosure_url_kept_raw_with_query():
    # A tracking query param must survive — it is the playable asset URL, not a
    # shareable article link, so sanitize_link is deliberately NOT applied.
    entry = feedparser.parse(PODCAST_RSS).entries[0]
    assert "?t=trackingid" in _audio_enclosure_url(entry)


# --- _entry_to_item --------------------------------------------------------

def _fetched_at() -> datetime:
    return datetime(2026, 6, 12, tzinfo=timezone.utc)


class _NoCursorRepo:
    def get_source_cursor(self, source_id):
        return None


def _ingestion() -> RSSIngestionService:
    return RSSIngestionService(_NoCursorRepo())


def test_entry_to_item_podcast_carries_kind_audio_duration():
    source = SourceDefinition(
        id="pod-x", name="Pod X", rss_url="https://pod.example/feed", kind="podcast"
    )
    entries = feedparser.parse(PODCAST_RSS).entries
    item = _ingestion()._entry_to_item(source, entries[0], _fetched_at())
    assert item is not None
    assert item.kind == "podcast"
    assert item.audio_url == "https://cdn.example/ep1.mp3?t=trackingid"
    assert item.audio_duration_seconds == 3600 + 25 * 60 + 15
    # Article link (not the audio URL) still gets its auth token stripped.
    assert "token" not in item.link


def test_entry_to_item_article_defaults_kind_and_no_audio():
    source = SourceDefinition(id="blog", name="Blog", rss_url="https://blog.example/feed")
    entry = feedparser.parse(ARTICLE_RSS).entries[0]
    item = _ingestion()._entry_to_item(source, entry, _fetched_at())
    assert item is not None
    assert item.kind == "article"
    assert item.audio_url is None
    assert item.audio_duration_seconds is None


# --- prompt attribution ----------------------------------------------------

def _podcast_item() -> SourceItem:
    return SourceItem(
        source_id="pod-pm",
        source_name="Planet Money",
        guid="g1",
        link="https://pod.example/pm1",
        title="Why rent is high",
        summary="An episode about housing costs.",
        published_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
        dedupe_key="g1",
        kind="podcast",
        audio_url="https://cdn.example/pm1.mp3",
        audio_duration_seconds=1500,
    )


def _article_item() -> SourceItem:
    return SourceItem(
        source_id="news-x",
        source_name="Source A",
        guid="a1",
        link="https://news.example/a",
        title="A headline",
        summary="A story.",
        published_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
        dedupe_key="a1",
    )


def _run_date():
    return datetime(2026, 6, 11, tzinfo=timezone.utc).date()


def test_prompt_labels_podcast_groups_and_adds_attribution():
    prompt = build_digest_prompt([_podcast_item()], run_date=_run_date(), ux=PodcastUxConfig())
    assert "Podcast: Planet Money" in prompt
    assert "Source: Planet Money" not in prompt
    assert "come from a podcast" in prompt


def test_prompt_articles_keep_source_label_and_no_podcast_note():
    prompt = build_digest_prompt([_article_item()], run_date=_run_date(), ux=PodcastUxConfig())
    assert "Source: Source A" in prompt
    assert "Podcast:" not in prompt
    assert "come from a podcast" not in prompt


def test_prompt_mixed_set_labels_each_group():
    prompt = build_digest_prompt(
        [_podcast_item(), _article_item()], run_date=_run_date(), ux=PodcastUxConfig()
    )
    assert "Podcast: Planet Money" in prompt
    assert "Source: Source A" in prompt
    assert "come from a podcast" in prompt


# --- persistence round-trip ------------------------------------------------

class _FakeSourceItemRepo:
    def __init__(self):
        self.saved = []

    def get_source_items(self, dedupe_keys):
        return []

    def upsert_source_items(self, records):
        self.saved = list(records)


def test_persistence_carries_podcast_fields():
    repo = _FakeSourceItemRepo()
    service = SourceItemPersistenceService(repo, embeddings=None)
    records = service.persist([_podcast_item()])
    assert len(records) == 1
    rec = records[0]
    assert rec.kind == "podcast"
    assert rec.audio_url == "https://cdn.example/pm1.mp3"
    assert rec.audio_duration_seconds == 1500


# --- shipped catalog guard -------------------------------------------------

def test_shipped_catalog_has_podcasts():
    sources = load_sources("sources.yml")
    pods = [s for s in sources if s.kind == "podcast"]
    assert len(pods) >= 10, f"expected the podcast catalog, got {len(pods)}"
    assert all(s.topic == "Podcasts" for s in pods)
    assert len({s.id for s in sources}) == len(sources), "duplicate source ids"


# --- backward compatibility ------------------------------------------------

def test_legacy_records_deserialize_with_defaults():
    # Firestore docs written before Phase 1a have no kind/audio fields; they
    # must still load, defaulting to article with no audio. Guards against a
    # future change of these fields from defaulted to required.
    rec = SourceItemRecord.model_validate(
        {
            "dedupe_key": "k",
            "source_id": "s",
            "source_name": "S",
            "link": "https://x.example/y",
            "title": "T",
            "summary": "body",
            "published_at": "2026-06-10T00:00:00+00:00",
            "first_seen_at": "2026-06-10T00:00:00+00:00",
            "last_seen_at": "2026-06-10T00:00:00+00:00",
        }
    )
    assert rec.kind == "article"
    assert rec.audio_url is None
    assert rec.audio_duration_seconds is None

    usr = UserSourceRecord.model_validate(
        {
            "id": "u:s",
            "user_id": "u",
            "source_id": "s",
            "name": "S",
            "rss_url": "https://x.example/feed",
            "created_at": "2026-06-10T00:00:00+00:00",
            "updated_at": "2026-06-10T00:00:00+00:00",
        }
    )
    assert usr.kind == "article"


# --- kind survives the attach -> store -> rebuild round-trip ----------------

class _PollSettings:
    candidate_queue_enabled = True
    podcast_bootstrap_max_items_per_source = 3
    next_episode_max_pins = 3
    next_episode_candidates_lookback_days = 14
    next_episode_candidates_limit = 50
    swipe_ranker_enabled = False
    swipe_ranker_min_swipes = 3


def test_poll_rebuilds_source_definition_with_podcast_kind(monkeypatch):
    # The load-bearing path: a stored UserSourceRecord with kind='podcast' must
    # rebuild into a SourceDefinition that still carries kind='podcast' when the
    # poll job re-derives the source list. Dropping kind= at the rebuild site
    # would silently fall back to 'article'; this catches that.
    repo = InMemoryControlPlaneRepository()
    now = utc_now()
    repo.replace_user_sources(
        "u-1",
        [
            UserSourceRecord(
                id="u-1:pod-x",
                user_id="u-1",
                source_id="pod-x",
                name="Pod X",
                rss_url="https://pod.example/feed",
                kind="podcast",
                created_at=now,
                updated_at=now,
            )
        ],
    )
    service = CandidateQueueService(
        settings=_PollSettings(),
        repository=repo,
        source_item_persistence=SourceItemPersistenceService(repository=repo, embeddings=None),
    )
    seen_kinds: dict[str, str] = {}

    class FakeIngestion:
        def __init__(self, repository, bootstrap_max_items_per_source):
            pass

        def fetch_new_items(self, sources):
            for s in sources:
                seen_kinds[s.id] = s.kind
            return IngestionResult(items=[], cursor_updates={})

    monkeypatch.setattr("newsletter_pod.candidate_queue.RSSIngestionService", FakeIngestion)
    service.run_poll(now_utc=now)
    assert seen_kinds.get("pod-x") == "podcast"
