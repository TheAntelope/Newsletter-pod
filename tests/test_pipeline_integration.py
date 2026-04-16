from __future__ import annotations

from datetime import datetime, timezone

from newsletter_pod.models import GeneratedEpisode, PublishStatus
from newsletter_pod.podcast_api import PodcastApiUnavailable


class TimeoutPodcastClient:
    enabled = True

    def generate(self, prompt: str, title: str) -> GeneratedEpisode:
        raise TimeoutError("generation timed out")


class UnavailablePodcastClient:
    enabled = False

    def generate(self, prompt: str, title: str) -> GeneratedEpisode:
        raise PodcastApiUnavailable("allowlist pending")


def _set_source_cursors(repository):
    repository.update_source_cursors(
        {
            "source-a": datetime(2026, 3, 8, 0, 0, tzinfo=timezone.utc),
            "source-b": datetime(2026, 3, 8, 0, 0, tzinfo=timezone.utc),
        }
    )


def _mock_entries_for_sources(monkeypatch, ingestion):
    entries = {
        "https://example.com/a.xml": [
            {
                "id": "guid-a",
                "link": "https://example.com/a",
                "title": "Alpha",
                "summary": "Alpha summary",
                "published": "Mon, 09 Mar 2026 05:10:00 GMT",
            }
        ],
        "https://example.com/b.xml": [
            {
                "id": "guid-b",
                "link": "https://example.com/b",
                "title": "Beta",
                "summary": "Beta summary",
                "published": "Mon, 09 Mar 2026 05:12:00 GMT",
            }
        ],
    }
    monkeypatch.setattr(ingestion, "_fetch_entries", lambda url: entries[url])


def test_pipeline_publishes_episode_and_stores_metadata_only(monkeypatch, pipeline_components):
    repository = pipeline_components["repository"]
    ingestion = pipeline_components["ingestion"]
    pipeline = pipeline_components["pipeline"]
    mailer = pipeline_components["mailer"]

    _set_source_cursors(repository)
    _mock_entries_for_sources(monkeypatch, ingestion)

    result = pipeline.run_daily_digest(now_utc=datetime(2026, 3, 9, 5, 35, tzinfo=timezone.utc))

    assert result.status == PublishStatus.PUBLISHED
    episodes = repository.list_recent_episodes(limit=10)
    assert len(episodes) == 1

    persisted = episodes[0].model_dump()
    assert persisted["title"] == "2026-03-09: AI, Startups, and Market Signals"
    assert "Generated digest summary" in persisted["description"]
    assert persisted["source_item_refs"]
    assert "summary" not in persisted["source_item_refs"][0]
    assert any("Newsletter digest published" in subject for subject, _ in mailer.messages)
    assert any("/feed/secret-token.xml" in body for _, body in mailer.messages)
    assert any("/media/secret-token/" in body for _, body in mailer.messages)


def test_pipeline_thin_day_still_publishes_short_episode(monkeypatch, pipeline_components):
    repository = pipeline_components["repository"]
    ingestion = pipeline_components["ingestion"]
    pipeline = pipeline_components["pipeline"]

    repository.update_source_cursors(
        {"source-a": datetime(2026, 3, 8, 0, 0, tzinfo=timezone.utc)}
    )
    monkeypatch.setattr(
        ingestion,
        "_fetch_entries",
        lambda _: [
            {
                "id": "guid-a",
                "link": "https://example.com/a",
                "title": "Alpha",
                "summary": "Alpha summary",
                "published": "Mon, 09 Mar 2026 05:10:00 GMT",
            }
        ],
    )

    result = pipeline.run_daily_digest(now_utc=datetime(2026, 3, 9, 5, 35, tzinfo=timezone.utc))

    assert result.status == PublishStatus.PUBLISHED
    episodes = repository.list_recent_episodes(limit=10)
    assert len(episodes) == 1


def test_pipeline_bootstraps_day_one_with_latest_items(monkeypatch, pipeline_components):
    repository = pipeline_components["repository"]
    ingestion = pipeline_components["ingestion"]
    pipeline = pipeline_components["pipeline"]

    entries = {
        "https://example.com/a.xml": [
            {
                "id": "guid-a1",
                "link": "https://example.com/a1",
                "title": "Alpha 1",
                "summary": "Alpha summary 1",
                "published": "Mon, 09 Mar 2026 05:00:00 GMT",
            },
            {
                "id": "guid-a2",
                "link": "https://example.com/a2",
                "title": "Alpha 2",
                "summary": "Alpha summary 2",
                "published": "Mon, 09 Mar 2026 05:10:00 GMT",
            },
            {
                "id": "guid-a3",
                "link": "https://example.com/a3",
                "title": "Alpha 3",
                "summary": "Alpha summary 3",
                "published": "Mon, 09 Mar 2026 05:20:00 GMT",
            },
            {
                "id": "guid-a4",
                "link": "https://example.com/a4",
                "title": "Alpha 4",
                "summary": "Alpha summary 4",
                "published": "Mon, 09 Mar 2026 05:30:00 GMT",
            },
        ],
        "https://example.com/b.xml": [
            {
                "id": "guid-b1",
                "link": "https://example.com/b1",
                "title": "Beta 1",
                "summary": "Beta summary 1",
                "published": "Mon, 09 Mar 2026 05:05:00 GMT",
            },
            {
                "id": "guid-b2",
                "link": "https://example.com/b2",
                "title": "Beta 2",
                "summary": "Beta summary 2",
                "published": "Mon, 09 Mar 2026 05:15:00 GMT",
            },
        ],
    }
    monkeypatch.setattr(ingestion, "_fetch_entries", lambda url: entries[url])

    result = pipeline.run_daily_digest(now_utc=datetime(2026, 3, 9, 5, 35, tzinfo=timezone.utc))

    assert result.status == PublishStatus.PUBLISHED
    assert result.candidate_count == 5
    episodes = repository.list_recent_episodes(limit=10)
    assert len(episodes) == 1


def test_pipeline_failure_then_cutoff_sends_alert(monkeypatch, pipeline_components):
    repository = pipeline_components["repository"]
    ingestion = pipeline_components["ingestion"]
    pipeline = pipeline_components["pipeline"]
    mailer = pipeline_components["mailer"]

    _set_source_cursors(repository)
    _mock_entries_for_sources(monkeypatch, ingestion)
    pipeline.podcast_client = TimeoutPodcastClient()

    first = pipeline.run_daily_digest(now_utc=datetime(2026, 3, 9, 5, 35, tzinfo=timezone.utc))
    assert first.status == PublishStatus.FAILED

    second = pipeline.run_daily_digest(now_utc=datetime(2026, 3, 9, 22, 10, tzinfo=timezone.utc))
    assert second.status == PublishStatus.SKIPPED
    assert any("failed before cutoff" in subject for subject, _ in mailer.messages)


def test_pre_access_mode_sends_status_email_and_no_episode(monkeypatch, pipeline_components):
    repository = pipeline_components["repository"]
    ingestion = pipeline_components["ingestion"]
    pipeline = pipeline_components["pipeline"]
    mailer = pipeline_components["mailer"]

    _set_source_cursors(repository)
    _mock_entries_for_sources(monkeypatch, ingestion)
    pipeline.podcast_client = UnavailablePodcastClient()

    result = pipeline.run_daily_digest(now_utc=datetime(2026, 3, 9, 5, 40, tzinfo=timezone.utc))

    assert result.status == PublishStatus.PRE_ACCESS
    assert repository.list_recent_episodes(limit=10) == []
    assert any("waiting for Podcast API access" in subject for subject, _ in mailer.messages)
