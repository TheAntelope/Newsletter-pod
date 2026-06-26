"""Validate candidate climate / environment default-source RSS URLs.

Mirrors the backend's `_build_custom_source_from_url` logic so the result
predicts what the production validate endpoint would do for each URL. Same
shape as validate_candidate_sources.py — run before adding any of these to
sources.yml (see CLAUDE.md: validate new sources end-to-end first).

Run:
    python scripts/validate_candidate_sources_climate.py
"""
from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import feedparser
import requests

CANDIDATES: dict[str, list[tuple[str, str]]] = {
    "Climate": [
        # --- Climate-dedicated newsrooms / analysis ---
        ("Carbon Brief", "https://www.carbonbrief.org/feed/"),
        ("Inside Climate News", "https://insideclimatenews.org/feed/"),
        ("Grist", "https://grist.org/feed/"),
        ("Yale Climate Connections", "https://yaleclimateconnections.org/feed/"),
        ("Climate Home News", "https://www.climatechangenews.com/feed/"),
        ("Canary Media", "https://www.canarymedia.com/articles.rss"),
        ("DeSmog", "https://www.desmog.com/feed/"),
        ("Mongabay", "https://news.mongabay.com/feed/"),
        # --- Clean energy / cleantech ---
        ("CleanTechnica", "https://cleantechnica.com/feed/"),
        # --- Major-outlet environment desks ---
        ("The Guardian Environment", "https://www.theguardian.com/environment/rss"),
        ("NASA Climate", "https://climate.nasa.gov/news/rss.xml"),
        ("The Conversation – Environment", "https://theconversation.com/global/environment/articles.atom"),
    ],
}


@dataclass
class Result:
    grouping: str
    name: str
    url: str
    ok: bool
    entries: int
    title: str
    error: str
    elapsed_ms: int


def validate(grouping: str, name: str, url: str) -> Result:
    t0 = time.time()
    try:
        # Mirror backend: requests.get(rss_url, timeout=20) — but add a UA
        # since some publishers 403 default-UA scrapers.
        resp = requests.get(
            url,
            timeout=20,
            headers={"User-Agent": "Mozilla/5.0 (compatible; ClawCastValidator/1.0)"},
        )
        resp.raise_for_status()
        parsed = feedparser.parse(resp.text)
        entries = list(parsed.entries)
        if not entries:
            return Result(grouping, name, url, False, 0, "", "no entries in feed", int((time.time() - t0) * 1000))
        title = parsed.feed.get("title") or ""
        return Result(grouping, name, url, True, len(entries), title, "", int((time.time() - t0) * 1000))
    except requests.HTTPError as e:
        return Result(grouping, name, url, False, 0, "", f"HTTP {e.response.status_code}", int((time.time() - t0) * 1000))
    except requests.RequestException as e:
        return Result(grouping, name, url, False, 0, "", f"{type(e).__name__}: {e}"[:120], int((time.time() - t0) * 1000))
    except Exception as e:
        return Result(grouping, name, url, False, 0, "", f"{type(e).__name__}: {e}"[:120], int((time.time() - t0) * 1000))


def main() -> int:
    jobs = [(g, n, u) for g, srcs in CANDIDATES.items() for n, u in srcs]
    print(f"Validating {len(jobs)} candidate sources across {len(CANDIDATES)} groupings...\n", flush=True)

    results: list[Result] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(validate, g, n, u): (g, n, u) for g, n, u in jobs}
        for fut in as_completed(futures):
            results.append(fut.result())

    by_grouping: dict[str, list[Result]] = {}
    for r in results:
        by_grouping.setdefault(r.grouping, []).append(r)

    total_ok = sum(1 for r in results if r.ok)
    print(f"=== Summary: {total_ok}/{len(results)} OK ===\n")

    for grouping in CANDIDATES.keys():
        rs = sorted(by_grouping.get(grouping, []), key=lambda r: (not r.ok, r.name))
        ok_count = sum(1 for r in rs if r.ok)
        print(f"## {grouping} ({ok_count}/{len(rs)} OK)")
        for r in rs:
            tag = "OK " if r.ok else "FAIL"
            detail = f"entries={r.entries} title={r.title!r}" if r.ok else f"err={r.error}"
            print(f"  [{tag}] {r.name:42s} {r.elapsed_ms:>5}ms  {detail}")
            print(f"         {r.url}")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
