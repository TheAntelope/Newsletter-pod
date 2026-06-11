"""Validate candidate cybersecurity / CVE default-source RSS URLs.

Mirrors the backend's `_build_custom_source_from_url` logic so the result
predicts what the production validate endpoint would do for each URL. Same
shape as validate_candidate_sources.py — run before adding any of these to
sources.yml (see CLAUDE.md: validate new sources end-to-end first).

Run:
    python scripts/validate_candidate_sources_cybersecurity.py
"""
from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import feedparser
import requests

CANDIDATES: dict[str, list[tuple[str, str]]] = {
    "Cybersecurity": [
        # --- CVE / advisory feeds (authoritative vuln announcements) ---
        ("CISA Cybersecurity Advisories", "https://www.cisa.gov/cybersecurity-advisories/all.xml"),
        ("SANS Internet Storm Center", "https://isc.sans.edu/rssfeed_full.xml"),
        ("Zero Day Initiative (Published)", "https://www.zerodayinitiative.com/rss/published/"),
        ("NVD Recent CVEs (cvefeed.io)", "https://cvefeed.io/rssfeed/latest.xml"),
        ("Google Project Zero", "https://googleprojectzero.blogspot.com/feeds/posts/default"),
        # --- News / analysis (context around active exploitation) ---
        ("The Hacker News", "https://feeds.feedburner.com/TheHackersNews"),
        ("BleepingComputer", "https://www.bleepingcomputer.com/feed/"),
        ("Krebs on Security", "https://krebsonsecurity.com/feed/"),
        ("Dark Reading", "https://www.darkreading.com/rss.xml"),
        ("SecurityWeek", "https://www.securityweek.com/feed/"),
        ("The Record (Recorded Future)", "https://therecord.media/feed"),
        ("Schneier on Security", "https://www.schneier.com/feed/atom/"),
        ("Cisco Talos Intelligence", "https://blog.talosintelligence.com/rss/"),
        ("Help Net Security", "https://www.helpnetsecurity.com/feed/"),
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
