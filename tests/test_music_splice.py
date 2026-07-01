from __future__ import annotations

import newsletter_pod.podcast_api as papi
from newsletter_pod.audio_mastering import MasteringError, _build_music_filter, splice_music
from newsletter_pod.blueprint import SectionDef, ShowBlueprint
from newsletter_pod.models import PodcastUxConfig
from newsletter_pod.podcast_api import PodcastApiClient


# --- pure filtergraph construction ------------------------------------------

def test_filter_neither_is_empty():
    fc, label = _build_music_filter(
        has_intro=False, has_outro=False, intro_bed_seconds=4, music_gain_db=-18, fade_ms=800
    )
    assert fc == "" and label == ""


def test_filter_intro_only_delays_speech_and_mixes():
    fc, label = _build_music_filter(
        has_intro=True, has_outro=False, intro_bed_seconds=4, music_gain_db=-18, fade_ms=800
    )
    assert label == "[out]"
    assert "[1:a]volume=-18dB" in fc  # intro is input 1, ducked
    assert "adelay=4000:all=1" in fc  # speech delayed by the bed
    assert "amix=inputs=2:normalize=0" in fc
    assert "acrossfade" not in fc  # no outro -> no crossfade


def test_filter_outro_only_crossfades_speech():
    fc, label = _build_music_filter(
        has_intro=False, has_outro=True, intro_bed_seconds=4, music_gain_db=-12, fade_ms=500
    )
    assert label == "[out]"
    assert "[1:a]volume=-12dB" in fc  # outro is input 1 when no intro
    assert "[0:a][outrobed]acrossfade=d=0.5" in fc
    assert "adelay" not in fc and "amix" not in fc


def test_filter_both_uses_intro_index_1_and_outro_index_2():
    fc, label = _build_music_filter(
        has_intro=True, has_outro=True, intro_bed_seconds=3, music_gain_db=-18, fade_ms=800
    )
    assert label == "[out]"
    assert "[1:a]volume=-18dB" in fc  # intro input 1
    assert "[2:a]volume=-18dB" in fc  # outro input 2
    assert "[body]" in fc  # intro+speech mix feeds the outro crossfade
    assert "acrossfade" in fc


def test_splice_music_noop_when_no_beds():
    # Neither intro nor outro -> returns input unchanged, never touches ffmpeg.
    assert splice_music(b"SPEECH") == b"SPEECH"


# --- _apply_music fallback / no-op behavior ---------------------------------

def _client() -> PodcastApiClient:
    return PodcastApiClient(
        enabled=True,
        provider="openai",
        base_url="https://api.openai.com",
        api_key="k",
        timeout_seconds=60,
        poll_seconds=5,
        text_model="m",
        tts_model="t",
        tts_voice="alloy",
    )


def _music_ux(intro: str | None = "music/intro.mp3", outro: str | None = None) -> PodcastUxConfig:
    bp = ShowBlueprint(sections=[SectionDef(kind="story_block"), SectionDef(kind="closing")])
    bp.opening.intro_music_enabled = intro is not None
    bp.opening.intro_music_asset = intro
    bp.music.outro_music_enabled = outro is not None
    bp.music.outro_music_asset = outro
    return PodcastUxConfig(blueprint=bp)


def test_apply_music_returns_original_when_splice_fails(monkeypatch):
    monkeypatch.setattr(
        papi, "splice_music", lambda *a, **k: (_ for _ in ()).throw(MasteringError("no ffmpeg"))
    )
    client = _client()
    loaded = []
    out = client._apply_music(b"SPEECH", _music_ux(), lambda name: loaded.append(name) or b"MUSIC")
    assert out == b"SPEECH"  # graceful fallback to un-music'd audio
    assert loaded == ["music/intro.mp3"]  # loader was consulted for the asset


def test_apply_music_returns_spliced_on_success(monkeypatch):
    monkeypatch.setattr(papi, "splice_music", lambda audio, **k: b"MUSIC:" + audio)
    client = _client()
    out = client._apply_music(b"SPEECH", _music_ux(intro="music/intro.mp3", outro="music/outro.mp3"),
                              lambda name: b"BED")
    assert out == b"MUSIC:SPEECH"


def test_apply_music_noop_without_blueprint_or_loader(monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(papi, "splice_music", lambda *a, **k: called.__setitem__("n", called["n"] + 1) or b"X")
    client = _client()
    # No loader
    assert client._apply_music(b"S", _music_ux(), None) == b"S"
    # No blueprint
    assert client._apply_music(b"S", PodcastUxConfig(), lambda n: b"B") == b"S"
    # Blueprint present but music disabled
    assert client._apply_music(b"S", _music_ux(intro=None, outro=None), lambda n: b"B") == b"S"
    assert called["n"] == 0  # splice_music never invoked on any no-op path
