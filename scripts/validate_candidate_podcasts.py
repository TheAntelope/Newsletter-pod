"""End-to-end validation of candidate podcast RSS feeds before they go into
the default catalog (sources.yml) as `kind: podcast` sources.

Beyond the article-feed checks in validate_candidate_sources.py, a podcast
feed must also reliably carry, on its recent items:
  * an <enclosure> with an audio/* type (the episode audio_url), and
  * an <itunes:duration> we can parse to seconds.

We also report show-note length (the Phase 1a content signal) and whether the
feed publishes a <podcast:transcript> (the Phase 1b content signal) so we can
prioritise transcript-rich feeds when 1b lands. A feed only PASSES if every one
of its most-recent items carries audio and it has published within RECENT_DAYS.

Run:
    python scripts/validate_candidate_podcasts.py
"""
from __future__ import annotations

import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone

import feedparser
import requests

# Use the SAME extraction logic the production ingester runs, so this pre-flight
# pass-gate can never drift from what the app will actually pull from a feed.
from newsletter_pod.ingestion import _audio_enclosure_url, _parse_itunes_duration

# (suggested_id, display_name, rss_url, region_or_None)
# region is an ISO 3166-1 alpha-2 code used to bias the onboarding deck; None =
# globally relevant. All of these land under the single "Podcasts" topic.
CANDIDATES: list[tuple[str, str, str, str | None]] = [
    # News / daily
    ("pod-up-first", "Up First (NPR)", "https://feeds.npr.org/510318/podcast.xml", "US"),
    ("pod-the-daily", "The Daily (NYT)", "https://feeds.simplecast.com/54nAGcIl", "US"),
    ("pod-global-news", "Global News Podcast (BBC)", "https://podcasts.files.bbci.co.uk/p02nq0gn.rss", "GB"),
    ("pod-newscast", "Newscast (BBC)", "https://podcasts.files.bbci.co.uk/p05299nl.rss", "GB"),
    # Business / economics
    ("pod-planet-money", "Planet Money (NPR)", "https://feeds.npr.org/510289/podcast.xml", "US"),
    ("pod-the-indicator", "The Indicator from Planet Money", "https://feeds.npr.org/510325/podcast.xml", "US"),
    ("pod-freakonomics", "Freakonomics Radio", "https://feeds.simplecast.com/Y8lFbOT4", None),
    # Tech
    ("pod-vergecast", "The Vergecast", "https://feeds.megaphone.fm/vergecast", None),
    ("pod-lex-fridman", "Lex Fridman Podcast", "https://lexfridman.com/feed/podcast/", None),
    # Science
    ("pod-short-wave", "Short Wave (NPR)", "https://feeds.npr.org/510351/podcast.xml", "US"),
    ("pod-radiolab", "Radiolab", "https://feeds.simplecast.com/EmVW7VGp", "US"),
    # Culture / ideas
    ("pod-ted-radio-hour", "TED Radio Hour (NPR)", "https://feeds.npr.org/510298/podcast.xml", "US"),
    ("pod-fresh-air", "Fresh Air (NPR)", "https://feeds.npr.org/381444908/podcast.xml", "US"),
    ("pod-ted-talks-daily", "TED Talks Daily", "https://feeds.feedburner.com/TEDTalks_audio", None),
    # Health & wellness
    ("pod-huberman-lab", "Huberman Lab", "https://feeds.megaphone.fm/hubermanlab", None),
    # Politics
    ("pod-pod-save-america", "Pod Save America", "https://feeds.simplecast.com/dxZsm5kX", "US"),
    ("pod-meidastouch", "The MeidasTouch Podcast", "https://feeds.megaphone.fm/PDR2572281095", "US"),
]

RECENT_DAYS = 45
RECENT_ITEMS = 5  # how many of the newest items we inspect for audio coverage
USER_AGENT = "Mozilla/5.0 (compatible; ClawCastValidator/1.0)"


def _published_dt(entry: dict) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    try:
        return datetime(*parsed[:6], tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


@dataclass
class Result:
    suggested_id: str
    name: str
    url: str
    region: str | None
    ok: bool = False
    feed_title: str = ""
    entries: int = 0
    audio_coverage: str = ""  # "5/5" of recent items carrying audio
    latest_age_days: int | None = None
    median_duration_min: int | None = None
    median_note_chars: int | None = None
    has_transcript: bool = False
    reasons: list[str] = field(default_factory=list)
    elapsed_ms: int = 0


def validate(suggested_id: str, name: str, url: str, region: str | None) -> Result:
    t0 = time.time()
    r = Result(suggested_id=suggested_id, name=name, url=url, region=region)
    try:
        resp = requests.get(url, timeout=20, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        parsed = feedparser.parse(resp.text)
        entries = list(parsed.entries)
        r.entries = len(entries)
        r.feed_title = parsed.feed.get("title") or ""
        if not entries:
            r.reasons.append("no entries")
            return r

        recent = entries[:RECENT_ITEMS]
        with_audio = sum(1 for e in recent if _audio_enclosure_url(e))
        r.audio_coverage = f"{with_audio}/{len(recent)}"

        durations = [d for e in recent if (d := _parse_itunes_duration(e.get("itunes_duration"))) is not None]
        if durations:
            r.median_duration_min = round(statistics.median(durations) / 60)

        note_lens = [len((e.get("summary") or e.get("description") or "")) for e in recent]
        if note_lens:
            r.median_note_chars = int(statistics.median(note_lens))

        r.has_transcript = any(e.get("podcast_transcript") for e in recent)

        dates = [d for e in entries if (d := _published_dt(e))]
        if dates:
            r.latest_age_days = (datetime.now(timezone.utc) - max(dates)).days

        # PASS gate: every recent item must carry audio, and the feed must be live.
        if with_audio < len(recent):
            r.reasons.append(f"audio coverage {r.audio_coverage}")
        if r.latest_age_days is None:
            r.reasons.append("no parseable dates")
        elif r.latest_age_days > RECENT_DAYS:
            r.reasons.append(f"stale (latest {r.latest_age_days}d old)")
        r.ok = not r.reasons
        return r
    except requests.HTTPError as e:
        r.reasons.append(f"HTTP {e.response.status_code}")
    except requests.RequestException as e:
        r.reasons.append(f"{type(e).__name__}: {e}"[:120])
    except Exception as e:  # pragma: no cover - diagnostic catch-all
        r.reasons.append(f"{type(e).__name__}: {e}"[:120])
    finally:
        r.elapsed_ms = int((time.time() - t0) * 1000)
    return r


def main() -> int:
    print(f"Validating {len(CANDIDATES)} candidate podcast feeds "
          f"(recent={RECENT_ITEMS} items, freshness<={RECENT_DAYS}d)...\n", flush=True)

    results: list[Result] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(validate, *c): c for c in CANDIDATES}
        for fut in as_completed(futures):
            results.append(fut.result())

    results.sort(key=lambda r: (not r.ok, r.name))
    total_ok = sum(1 for r in results if r.ok)
    print(f"=== Summary: {total_ok}/{len(results)} PASS ===\n")

    for r in results:
        tag = "PASS" if r.ok else "FAIL"
        print(f"[{tag}] {r.name:34s} {r.elapsed_ms:>5}ms  "
              f"audio={r.audio_coverage} age={r.latest_age_days}d "
              f"dur~{r.median_duration_min}m notes~{r.median_note_chars}c "
              f"transcript={'Y' if r.has_transcript else 'n'}")
        print(f"       id={r.suggested_id} region={r.region} title={r.feed_title!r}")
        if r.reasons:
            print(f"       reasons: {', '.join(r.reasons)}")
        print(f"       {r.url}")

    print("\n=== YAML for passing feeds (paste under sources.yml) ===\n")
    for r in results:
        if not r.ok:
            continue
        region_line = f"\n    region: {r.region}" if r.region else ""
        print(f"""  - id: {r.suggested_id}
    name: {r.name}{region_line}
    rss_url: {r.url}
    topic: Podcasts
    kind: podcast
    enabled: true
    ingest_mode: excerpt
    jurisdiction_sensitive: false
""")

    return 0


if __name__ == "__main__":
    sys.exit(main())
