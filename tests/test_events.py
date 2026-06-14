from __future__ import annotations

import json
import logging

import pytest
from fastapi.testclient import TestClient

from newsletter_pod import events as events_module
from newsletter_pod.events import (
    EventName,
    EventPIIError,
    bucket_play_position_seconds,
    is_bot_user_agent,
    log_event,
    normalize_platform,
    platform_from_user_agent,
)
from newsletter_pod.main import _build_container, create_app
from newsletter_pod.user_models import DeviceTokenRecord, UserEpisodeRecord


class FakeAppleVerifier:
    """Mirror of the one in test_control_plane_api.py so this file stays
    self-contained — no cross-test-module imports."""

    def __init__(self, subject: str, email: str) -> None:
        self.subject = subject
        self.email = email

    def verify(self, identity_token: str):
        return type(
            "Identity",
            (),
            {"subject": self.subject, "email": self.email},
        )()


def _build_app():
    from newsletter_pod.config import Settings

    settings = Settings.from_env()
    settings.use_inmemory_adapters = True
    settings.apple_client_id = "com.example.newsletterpod"
    settings.session_signing_secret = "test-session-secret-32-bytes-long"
    settings.podcast_api_enabled = False
    settings.job_trigger_token = None
    settings.app_base_url = "http://testserver"
    settings.publish_summary_email_enabled = False
    settings.free_max_delivery_days = 1
    settings.pro_max_delivery_days = 3
    settings.max_max_delivery_days = 3
    container = _build_container(settings)
    return container, TestClient(create_app(container=container))


def _auth_headers(client: TestClient, verifier: FakeAppleVerifier) -> tuple[str, dict[str, str]]:
    app = client.app
    app.state.container.control_plane.apple_identity_verifier = verifier
    response = client.post("/v1/auth/apple", json={"identity_token": "apple-token"})
    assert response.status_code == 200
    token = response.json()["session_token"]
    return token, {"Authorization": f"Bearer {token}"}


def _parse_event_record(record: logging.LogRecord) -> dict | None:
    """Decode an `app_event` JSON log message. Returns None for any record
    that isn't a JSON object with our `event` marker — so this also serves
    as a filter for other logger.info noise inside the same logger."""
    try:
        payload = json.loads(record.getMessage())
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or payload.get("event") != "app_event":
        return None
    return payload


def _captured_events(caplog: pytest.LogCaptureFixture) -> list[dict]:
    out = []
    for record in caplog.records:
        if record.name != events_module.__name__:
            continue
        decoded = _parse_event_record(record)
        if decoded is not None:
            out.append(decoded)
    return out


def test_log_event_emits_expected_shape(caplog):
    caplog.set_level(logging.INFO, logger=events_module.__name__)
    log_event(EventName.SIGN_IN, "user-123", is_new_user=True)

    events = _captured_events(caplog)
    assert len(events) == 1
    event = events[0]
    assert set(event.keys()) == {
        "event", "event_name", "user_id", "platform", "ts", "properties"
    }
    assert event["event"] == "app_event"
    assert event["event_name"] == "sign_in"
    assert event["user_id"] == "user-123"
    # No client header and no explicit platform -> null, not a crash.
    assert event["platform"] is None
    assert event["properties"] == {"is_new_user": True}
    # ts is ISO 8601, parseable
    from datetime import datetime

    parsed = datetime.fromisoformat(event["ts"])
    assert parsed.tzinfo is not None


def test_log_event_accepts_none_user_id(caplog):
    caplog.set_level(logging.INFO, logger=events_module.__name__)
    log_event(EventName.PAYWALL_VIEWED, None, surface="onboarding")
    events = _captured_events(caplog)
    assert len(events) == 1
    assert events[0]["user_id"] is None
    assert events[0]["event_name"] == "paywall_viewed"


def test_log_event_requires_event_name_enum():
    with pytest.raises(TypeError):
        log_event("sign_in", "user-1", is_new_user=True)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "key",
    ["email", "raw_text", "subject", "body_text", "transcript", "display_name"],
)
def test_log_event_refuses_pii_property_keys(key):
    with pytest.raises(EventPIIError) as excinfo:
        log_event(EventName.FEEDBACK_SUBMITTED, "user-1", **{key: "anything"})
    assert key in str(excinfo.value)


def test_log_event_pii_check_runs_before_log_is_emitted(caplog):
    caplog.set_level(logging.INFO, logger=events_module.__name__)
    with pytest.raises(EventPIIError):
        log_event(EventName.FEEDBACK_SUBMITTED, "user-1", email="user@example.com")
    assert _captured_events(caplog) == []


def test_bucket_play_position_seconds():
    assert bucket_play_position_seconds(0) == "0-30"
    assert bucket_play_position_seconds(29) == "0-30"
    assert bucket_play_position_seconds(30) == "30-120"
    assert bucket_play_position_seconds(119) == "30-120"
    assert bucket_play_position_seconds(120) == "120-600"
    assert bucket_play_position_seconds(599) == "120-600"
    assert bucket_play_position_seconds(600) == "600+"
    assert bucket_play_position_seconds(99_999) == "600+"


def test_play_pulse_endpoint_requires_auth():
    _, client = _build_app()
    resp = client.post(
        "/v1/me/episodes/ep-abc/play-pulse",
        json={"position_seconds": 45},
    )
    assert resp.status_code == 401


def test_play_pulse_endpoint_logs_event_with_bucket(caplog):
    _, client = _build_app()
    _, headers = _auth_headers(
        client, FakeAppleVerifier("pulse-user", "pulse@example.com")
    )

    caplog.set_level(logging.INFO, logger=events_module.__name__)
    resp = client.post(
        "/v1/me/episodes/ep-abc/play-pulse",
        json={"position_seconds": 150},
        headers=headers,
    )
    assert resp.status_code == 202
    assert resp.json() == {"accepted": True}

    pulses = [
        e for e in _captured_events(caplog)
        if e["event_name"] == EventName.EPISODE_PLAY_PULSE.value
    ]
    assert len(pulses) == 1
    pulse = pulses[0]
    assert pulse["properties"]["episode_id"] == "ep-abc"
    assert pulse["properties"]["position_bucket"] == "120-600"
    assert pulse["user_id"], "play-pulse must be tied to the authenticated user"


def test_play_pulse_endpoint_clamps_negative_positions(caplog):
    """A misbehaving client that posts a negative position should land
    in the 0-30 bucket rather than crashing the request."""
    _, client = _build_app()
    _, headers = _auth_headers(
        client, FakeAppleVerifier("pulse-neg-user", "pn@example.com")
    )

    caplog.set_level(logging.INFO, logger=events_module.__name__)
    resp = client.post(
        "/v1/me/episodes/ep-neg/play-pulse",
        json={"position_seconds": -42},
        headers=headers,
    )
    assert resp.status_code == 202
    pulses = [
        e for e in _captured_events(caplog)
        if e["event_name"] == EventName.EPISODE_PLAY_PULSE.value
    ]
    assert pulses and pulses[0]["properties"]["position_bucket"] == "0-30"


def test_sign_in_emits_event_via_auth_flow(caplog):
    _, client = _build_app()
    caplog.set_level(logging.INFO, logger=events_module.__name__)
    _, _ = _auth_headers(client, FakeAppleVerifier("evt-user", "evt@example.com"))

    sign_ins = [
        e for e in _captured_events(caplog) if e["event_name"] == EventName.SIGN_IN.value
    ]
    assert len(sign_ins) == 1
    assert sign_ins[0]["properties"] == {"is_new_user": True}


# ---------------------------------------------------------------------------
# Platform dimension
# ---------------------------------------------------------------------------


def test_log_event_explicit_platform_recorded_and_normalised(caplog):
    caplog.set_level(logging.INFO, logger=events_module.__name__)
    log_event(EventName.SIGN_IN, "user-1", platform="Android")
    events = _captured_events(caplog)
    assert events[0]["platform"] == "android"
    # platform is top-level, never leaked into properties.
    assert "platform" not in events[0]["properties"]


def test_log_event_unknown_platform_dropped_to_null(caplog):
    caplog.set_level(logging.INFO, logger=events_module.__name__)
    log_event(EventName.SIGN_IN, "user-1", platform="symbian")
    assert _captured_events(caplog)[0]["platform"] is None


def test_normalize_platform():
    assert normalize_platform("iOS") == "ios"
    assert normalize_platform(" ANDROID ") == "android"
    assert normalize_platform("web") == "web"
    assert normalize_platform("windows-phone") is None
    assert normalize_platform("") is None
    assert normalize_platform(None) is None


def test_platform_from_user_agent():
    # Apple Podcasts' real UA carries no applecoremedia/itunes token — the
    # CFNetwork/Darwin networking-stack markers are what catch it.
    assert platform_from_user_agent(
        "Podcasts/4025.610.1 CFNetwork/3860.600.12 Darwin/25.5.0"
    ) == "ios"
    assert platform_from_user_agent("AppleCoreMedia/1.0 (iPhone; CPU OS 18_0)") == "ios"
    assert platform_from_user_agent("iTunes/12.0") == "ios"
    assert platform_from_user_agent(
        "Overcast/3.0 (+http://overcast.fm/; iOS podcast app)"
    ) == "ios"
    assert platform_from_user_agent("atc/1.0 watchOS/26.5") == "ios"
    assert platform_from_user_agent(
        "Mozilla/5.0 (iPhone; CPU iPhone OS 26_5_0 like Mac OS X) EdgiOS/148"
    ) == "ios"
    assert platform_from_user_agent("PodcastAddict/v5 (Android 14)") == "android"
    assert platform_from_user_agent(
        "Snipd/4.1.14 Dalvik/2.1.0 (Linux; U; Android 16; motorola razr)"
    ) == "android"
    assert platform_from_user_agent("okhttp/5.3.2") == "android"
    # Cross-platform clients expose no OS token -> unknown (device-token fallback).
    assert platform_from_user_agent("Pocket Casts") is None
    assert platform_from_user_agent(None) is None


def test_is_bot_user_agent():
    assert is_bot_user_agent("WhatsApp/2.23.20.0") is True
    assert is_bot_user_agent(
        "Mozilla/5.0 (compatible; Discordbot/2.0; +https://discordapp.com)"
    ) is True
    assert is_bot_user_agent("WordPress.com - Audio/1.0") is True
    assert is_bot_user_agent("Pocket Casts") is False
    assert is_bot_user_agent("Podcasts/4025.610.1 CFNetwork/3860 Darwin/25.5.0") is False
    assert is_bot_user_agent(None) is False


def test_x_client_platform_header_tags_events(caplog):
    """End-to-end through the middleware: a client that sends
    X-Client-Platform gets every event for that request stamped with it."""
    _, client = _build_app()
    app = client.app
    app.state.container.control_plane.apple_identity_verifier = FakeAppleVerifier(
        "plat-user", "plat@example.com"
    )

    caplog.set_level(logging.INFO, logger=events_module.__name__)
    resp = client.post(
        "/v1/auth/apple",
        json={"identity_token": "apple-token"},
        headers={"X-Client-Platform": "android"},
    )
    assert resp.status_code == 200

    sign_ins = [
        e for e in _captured_events(caplog) if e["event_name"] == EventName.SIGN_IN.value
    ]
    assert sign_ins and sign_ins[0]["platform"] == "android"


def test_media_route_emits_listening_pulse_with_platform(caplog):
    """An external podcast app fetching audio from /media produces a
    server-side play-pulse tagged with the platform inferred from its
    User-Agent — the only cross-stack listening signal we get."""
    from datetime import datetime, timezone

    container, client = _build_app()
    _, headers = _auth_headers(
        client, FakeAppleVerifier("media-plat-user", "mp@example.com")
    )
    me = client.get("/v1/me", headers=headers).json()["user"]
    repo = container.control_repository
    storage = container.storage
    token = repo.get_feed_token(me["id"])

    audio = b"y" * 300_000  # ~37.5s at the assumed 8 KB/s
    object_name, size = storage.upload_audio("ep-plat", audio, "audio/mpeg")
    repo.save_user_episode(
        UserEpisodeRecord(
            id="ep-plat",
            user_id=me["id"],
            title="Plat Test",
            description="Notes",
            published_at=datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
            audio_object_name=object_name,
            audio_size_bytes=size,
        )
    )

    caplog.set_level(logging.INFO, logger=events_module.__name__)
    # Range starting 250 KB in ~= 31s at the assumed 8 KB/s, so it lands past
    # the intro bucket; Podcast Addict UA -> android.
    resp = client.get(
        f"/media/{token.token}/ep-plat.mp3",
        headers={
            "Range": "bytes=250000-",
            "User-Agent": "PodcastAddict/v5 (Android 14)",
        },
    )
    assert resp.status_code == 206

    pulses = [
        e for e in _captured_events(caplog)
        if e["event_name"] == EventName.EPISODE_PLAY_PULSE.value
    ]
    assert len(pulses) == 1
    pulse = pulses[0]
    assert pulse["platform"] == "android"
    assert pulse["user_id"] == me["id"]
    assert pulse["properties"]["episode_id"] == "ep-plat"
    assert pulse["properties"]["source"] == "media_fetch"
    # 250000 // 8000 = 31s -> the "30-120" (past-intro) bucket.
    assert pulse["properties"]["position_bucket"] == "30-120"


def test_media_head_request_emits_no_pulse(caplog):
    """HEAD is a metadata probe, not a listen — it must not emit a pulse."""
    from datetime import datetime, timezone

    container, client = _build_app()
    _, headers = _auth_headers(
        client, FakeAppleVerifier("media-head-user", "mh@example.com")
    )
    me = client.get("/v1/me", headers=headers).json()["user"]
    repo = container.control_repository
    storage = container.storage
    token = repo.get_feed_token(me["id"])
    object_name, size = storage.upload_audio("ep-head", b"z" * 1000, "audio/mpeg")
    repo.save_user_episode(
        UserEpisodeRecord(
            id="ep-head",
            user_id=me["id"],
            title="Head Test",
            description="Notes",
            published_at=datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
            audio_object_name=object_name,
            audio_size_bytes=size,
        )
    )

    caplog.set_level(logging.INFO, logger=events_module.__name__)
    resp = client.head(f"/media/{token.token}/ep-head.mp3")
    assert resp.status_code == 200
    pulses = [
        e for e in _captured_events(caplog)
        if e["event_name"] == EventName.EPISODE_PLAY_PULSE.value
    ]
    assert pulses == []


def _seed_media_episode(container, client, *, subject, email, episode_id):
    """Auth a fresh user and give them one playable episode; returns
    (user_id, feed_token)."""
    from datetime import datetime, timezone

    _, headers = _auth_headers(client, FakeAppleVerifier(subject, email))
    me = client.get("/v1/me", headers=headers).json()["user"]
    repo = container.control_repository
    storage = container.storage
    token = repo.get_feed_token(me["id"])
    object_name, size = storage.upload_audio(episode_id, b"q" * 1000, "audio/mpeg")
    repo.save_user_episode(
        UserEpisodeRecord(
            id=episode_id,
            user_id=me["id"],
            title="T",
            description="d",
            published_at=datetime(2026, 6, 14, 9, 0, tzinfo=timezone.utc),
            audio_object_name=object_name,
            audio_size_bytes=size,
        )
    )
    return me["id"], token


def test_media_route_device_token_fallback_for_ambiguous_ua(caplog):
    """A cross-platform client (Pocket Casts) has no OS token in its UA, so the
    listening pulse falls back to the user's stack from their device token."""
    from datetime import datetime, timezone

    container, client = _build_app()
    user_id, token = _seed_media_episode(
        container, client, subject="media-dt", email="dt@example.com",
        episode_id="ep-dt",
    )
    now = datetime(2026, 6, 14, 9, 0, tzinfo=timezone.utc)
    container.control_repository.save_device_token(
        DeviceTokenRecord(
            id=f"{user_id}::tok",
            user_id=user_id,
            token="devicetoken-abcd",
            platform="android",
            bundle_id="com.newsletterpod.app",
            created_at=now,
            last_seen_at=now,
        )
    )

    caplog.set_level(logging.INFO, logger=events_module.__name__)
    resp = client.get(
        f"/media/{token.token}/ep-dt.mp3",
        headers={"User-Agent": "Pocket Casts"},
    )
    assert resp.status_code == 200
    pulses = [
        e for e in _captured_events(caplog)
        if e["event_name"] == EventName.EPISODE_PLAY_PULSE.value
    ]
    assert len(pulses) == 1
    # UA was ambiguous -> platform resolved from the android device token.
    assert pulses[0]["platform"] == "android"


def test_media_route_skips_bot_user_agent(caplog):
    """A link-preview bot fetching the media URL is not a listen -> no pulse."""
    container, client = _build_app()
    _, token = _seed_media_episode(
        container, client, subject="media-bot", email="bot@example.com",
        episode_id="ep-bot",
    )

    caplog.set_level(logging.INFO, logger=events_module.__name__)
    resp = client.get(
        f"/media/{token.token}/ep-bot.mp3",
        headers={"User-Agent": "WhatsApp/2.23.20.0"},
    )
    assert resp.status_code == 200
    pulses = [
        e for e in _captured_events(caplog)
        if e["event_name"] == EventName.EPISODE_PLAY_PULSE.value
    ]
    assert pulses == []
