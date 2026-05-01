"""Round 2: retry failed sources with alternative URLs / fill thin groupings."""
from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import feedparser
import requests

CANDIDATES: dict[str, list[tuple[str, str]]] = {
    "News (need backups for AP/Reuters)": [
        ("CBS News", "https://www.cbsnews.com/latest/rss/main"),
        ("CNBC Top News", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114"),
        ("The Guardian US", "https://www.theguardian.com/us/rss"),
        ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
        ("AP via Google News", "https://news.google.com/rss/search?q=site:apnews.com&hl=en-US"),
    ],
    "Strategy (refilling)": [
        ("a16z (alt /?feed=rss2)", "https://a16z.com/?feed=rss2"),
        ("First Round Review (atom)", "https://review.firstround.com/atom.xml"),
        ("First Round Review (alt /feed/)", "https://review.firstround.com/feed/"),
        ("YC Blog", "https://www.ycombinator.com/blog/rss"),
        ("Andrew Chen", "https://andrewchen.com/feed/"),
        ("Future (a16z substack)", "https://future.com/feed/"),
        ("Both Sides of the Table (Mark Suster)", "https://bothsidesofthetable.com/feed"),
    ],
    "Health (refilling)": [
        ("Tim Ferriss Blog", "https://tim.blog/feed/"),
        ("MindBodyGreen", "https://www.mindbodygreen.com/feed.xml"),
        ("Healthline news", "https://www.healthline.com/rss/health-news"),
        ("Examine (alt)", "https://examine.com/rss/"),
        ("Huberman Lab (alt root /feed/)", "https://www.hubermanlab.com/feed"),
        ("Andrew Huberman podcast feed", "https://feeds.megaphone.fm/hubermanlab"),
    ],
    "Business (Hustle alt)": [
        ("The Hustle (alt /rss/)", "https://thehustle.co/rss/"),
        ("Morning Brew", "https://www.morningbrew.com/feed"),
    ],
    "Science (SciAm alt)": [
        ("SciAm (alt /feeds/news/)", "https://rss.sciam.com/sciam/60-second-science"),
        ("SciAm (alt /rss/)", "https://www.scientificamerican.com/platform/syndication/rss/"),
        ("SciAm rss/everything", "https://rss.sciam.com/sciam/everything"),
    ],
    "Sports (SI/Ringer alts)": [
        ("The Ringer (alt feed.xml)", "https://www.theringer.com/feed"),
        ("SI (alt /.rss)", "https://www.si.com/.rss/full"),
        ("The Athletic free", "https://theathletic.com/rss-feed/"),
        ("Bleacher Report", "https://syndication.bleacherreport.com/amp/articles.rss"),
    ],
    "Culture (Garbage Day / Atlantic alts)": [
        ("Garbage Day (alt substack)", "https://www.garbageday.email/feed.xml"),
        ("Garbage Day (root)", "https://garbageday.email/feed"),
        ("The Atlantic (Culture alt)", "https://www.theatlantic.com/feed/channel/culture/"),
    ],
    "Food & Travel (Stained Page / Serious Eats alt)": [
        ("Stained Page (substack alt)", "https://stainedpage.substack.com/feed"),
        ("Serious Eats (alt /atom.xml)", "https://www.seriouseats.com/atom.xml"),
        ("Saveur", "https://www.saveur.com/feed/"),
    ],
    "Romantasy (Frolic / Ripped Bodice alts)": [
        ("Frolic (alt /feed/)", "https://www.frolic.media/feed/"),
        ("The Ripped Bodice (RSS)", "https://www.therippedbodicela.com/blogs/news.atom"),
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
            return Result(grouping, name, url, False, 0, "", "no entries", int((time.time() - t0) * 1000))
        title = parsed.feed.get("title") or ""
        return Result(grouping, name, url, True, len(entries), title, "", int((time.time() - t0) * 1000))
    except requests.HTTPError as e:
        return Result(grouping, name, url, False, 0, "", f"HTTP {e.response.status_code}", int((time.time() - t0) * 1000))
    except requests.RequestException as e:
        return Result(grouping, name, url, False, 0, "", f"{type(e).__name__}: {str(e)[:80]}", int((time.time() - t0) * 1000))
    except Exception as e:
        return Result(grouping, name, url, False, 0, "", f"{type(e).__name__}: {str(e)[:80]}", int((time.time() - t0) * 1000))


def main() -> int:
    jobs = [(g, n, u) for g, srcs in CANDIDATES.items() for n, u in srcs]
    print(f"Round 2: {len(jobs)} candidates\n", flush=True)

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
            print(f"  [{tag}] {r.name:42s} {detail}")
            print(f"         {r.url}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
