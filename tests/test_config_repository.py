from __future__ import annotations

from datetime import datetime, timezone

from newsletter_pod import config_repository
from newsletter_pod.blueprint import SectionDef, ShowBlueprint, default_blueprint
from newsletter_pod.config import Settings
from newsletter_pod.config_repository import (
    BlueprintProvider,
    InMemoryBlueprintRepository,
)


def _bp(intro_music: bool = False) -> ShowBlueprint:
    bp = default_blueprint()
    bp.opening.intro_music_enabled = intro_music
    bp.opening.intro_music_asset = "music/intro.mp3" if intro_music else None
    return bp


def test_save_increments_version_and_records_history():
    repo = InMemoryBlueprintRepository()
    assert repo.get_active() is None

    v1 = repo.save_new_version(_bp(), updated_by="vince", note="first")
    v2 = repo.save_new_version(_bp(intro_music=True), updated_by="vince")

    assert v1.version == 1
    assert v2.version == 2
    assert repo.get_active().version == 2
    assert repo.get_active().blueprint.opening.intro_music_enabled is True
    history = repo.list_history()
    assert [r.version for r in history] == [2, 1]  # newest first


def test_restore_creates_new_version_not_a_rewind():
    repo = InMemoryBlueprintRepository()
    repo.save_new_version(_bp(intro_music=False))  # v1
    repo.save_new_version(_bp(intro_music=True))  # v2

    restored = repo.restore_version(1, updated_by="vince")

    assert restored.version == 3  # counter never rewinds
    assert restored.note == "restore of v1"
    assert restored.blueprint.opening.intro_music_enabled is False
    assert repo.get_active().version == 3


def test_restore_missing_version_returns_none():
    repo = InMemoryBlueprintRepository()
    repo.save_new_version(_bp())
    assert repo.restore_version(99) is None


def test_provider_returns_none_on_empty_store():
    # Deliberately None (not the default) so shipping the code is a no-op for
    # generation until an admin saves a blueprint.
    repo = InMemoryBlueprintRepository()
    provider = BlueprintProvider(repo, Settings())
    assert provider.get() is None


def test_provider_caches_within_ttl_and_refetches_after(monkeypatch):
    repo = InMemoryBlueprintRepository()
    repo.save_new_version(_bp(intro_music=False))
    provider = BlueprintProvider(repo, Settings(), ttl_seconds=60.0)

    clock = {"t": 1000.0}
    monkeypatch.setattr(config_repository.time, "monotonic", lambda: clock["t"])

    calls = {"n": 0}
    real_get_active = repo.get_active

    def counting_get_active():
        calls["n"] += 1
        return real_get_active()

    monkeypatch.setattr(repo, "get_active", counting_get_active)

    # First get fetches; second within TTL is served from cache.
    assert provider.get().opening.intro_music_enabled is False
    assert provider.get().opening.intro_music_enabled is False
    assert calls["n"] == 1

    # A new save while cached is NOT seen until the TTL lapses...
    repo.save_new_version(_bp(intro_music=True))
    assert provider.get().opening.intro_music_enabled is False
    assert calls["n"] == 1

    # ...then the window expires and the next get refetches the new value.
    clock["t"] += 61.0
    assert provider.get().opening.intro_music_enabled is True
    assert calls["n"] == 2


def test_provider_invalidate_forces_refetch(monkeypatch):
    repo = InMemoryBlueprintRepository()
    repo.save_new_version(_bp(intro_music=False))
    provider = BlueprintProvider(repo, Settings(), ttl_seconds=600.0)

    assert provider.get().opening.intro_music_enabled is False
    repo.save_new_version(_bp(intro_music=True))
    # Still cached...
    assert provider.get().opening.intro_music_enabled is False
    provider.invalidate()
    # ...invalidate makes the editing instance see the change immediately.
    assert provider.get().opening.intro_music_enabled is True


def test_save_records_timestamp():
    repo = InMemoryBlueprintRepository()
    stamp = datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc)
    rec = repo.save_new_version(_bp(), now=stamp)
    assert rec.updated_at == stamp
