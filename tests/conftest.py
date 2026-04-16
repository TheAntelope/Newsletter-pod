from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from newsletter_pod.ingestion import RSSIngestionService
from newsletter_pod.mailer import NoopMailer
from newsletter_pod.models import AudioSegment, GeneratedEpisode, SourceDefinition
from newsletter_pod.pipeline import DigestPipeline
from newsletter_pod.repository import InMemoryRepository
from newsletter_pod.retry_policy import RetryPolicy
from newsletter_pod.storage import InMemoryAudioStorage


class CapturingMailer(NoopMailer):
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def send(self, subject: str, body: str) -> None:
        self.messages.append((subject, body))


class SuccessPodcastClient:
    enabled = True

    def generate(self, prompt: str, title: str) -> GeneratedEpisode:
        return GeneratedEpisode(
            episode_title="2026-03-09: AI, Startups, and Market Signals",
            audio_bytes=b"fake-mp3-audio",
            mime_type="audio/mpeg",
            show_notes="Generated digest summary",
            audio_segments=[
                AudioSegment(speaker="Elena", text="Welcome to the briefing."),
                AudioSegment(speaker="Marcus", text="That is the key context today."),
            ],
            transcript="Elena: Welcome to the briefing.\n\nMarcus: That is the key context today.",
            duration_seconds=620,
        )


@pytest.fixture
def retry_policy() -> RetryPolicy:
    return RetryPolicy(
        timezone_name="Europe/Copenhagen",
        start_local="06:30",
        target_local="07:00",
        cutoff_local="23:00",
        rapid_retry_minutes=5,
        periodic_retry_minutes=30,
    )


@pytest.fixture
def source_defs() -> list[SourceDefinition]:
    return [
        SourceDefinition(
            id="source-a",
            name="Source A",
            rss_url="https://example.com/a.xml",
            enabled=True,
        ),
        SourceDefinition(
            id="source-b",
            name="Source B",
            rss_url="https://example.com/b.xml",
            enabled=True,
        ),
    ]


@pytest.fixture
def pipeline_components(retry_policy: RetryPolicy, source_defs: list[SourceDefinition]):
    repository = InMemoryRepository()
    storage = InMemoryAudioStorage()
    mailer = CapturingMailer()
    ingestion = RSSIngestionService(repository=repository)
    client = SuccessPodcastClient()

    pipeline = DigestPipeline(
        sources=source_defs,
        repository=repository,
        ingestion_service=ingestion,
        podcast_client=client,
        storage=storage,
        mailer=mailer,
        retry_policy=retry_policy,
        app_base_url="http://testserver",
        feed_token="secret-token",
        publish_summary_email_enabled=True,
    )

    return {
        "pipeline": pipeline,
        "repository": repository,
        "storage": storage,
        "mailer": mailer,
        "ingestion": ingestion,
    }


def utc_dt(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def local_date_from_utc(policy: RetryPolicy, now_utc: datetime) -> date:
    return policy.local_date(now_utc)
