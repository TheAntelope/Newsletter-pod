"""Validate space + fitness candidate RSS feeds before adding to defaults.

Space candidates expand the existing Science section. Fitness candidates
seed a brand-new top-level category requested by user feedback.
"""
from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import feedparser
import requests

CANDIDATES: dict[str, list[tuple[str, str]]] = {
    "Science (space additions)": [
        ("NASA Breaking News", "https://www.nasa.gov/news-release/feed/"),
        ("SpaceNews", "https://spacenews.com/feed/"),
        ("Space.com", "https://www.space.com/feeds/all"),
        ("The Planetary Society", "https://www.planetary.org/articles.rss"),
        ("Sky & Telescope", "https://skyandtelescope.org/astronomy-news/feed/"),
        ("Universe Today", "https://www.universetoday.com/feed/"),
        ("Phys.org Space News", "https://phys.org/rss-feed/space-news/"),
        ("ESA Top News", "https://www.esa.int/rssfeed/Our_Activities/Space_News"),
    ],
    "Fitness (new category)": [
        ("Outside Online", "https://www.outsideonline.com/rss"),
        ("Stronger by Science", "https://www.strongerbyscience.com/feed/"),
        ("Runner's World", "https://www.runnersworld.com/rss/all.xml/"),
        ("Marathon Handbook", "https://marathonhandbook.com/feed/"),
        ("Triathlete", "https://www.triathlete.com/feed/"),
        ("Barbell Medicine", "https://www.barbellmedicine.com/feed/"),
        ("Breaking Muscle", "https://breakingmuscle.com/feed/"),
        ("Men's Health (All)", "https://www.menshealth.com/rss/all.xml/"),
        ("Bicycling", "https://www.bicycling.com/rss/all.xml/"),
        ("Bodybuilding.com Articles", "https://www.bodybuilding.com/rss/articles"),
        ("Greatist", "https://greatist.com/rss"),
        ("Self Magazine", "https://www.self.com/feed/rss"),
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
    print(f"Validating {len(jobs)} candidates across {len(CANDIDATES)} groupings...\n", flush=True)

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
