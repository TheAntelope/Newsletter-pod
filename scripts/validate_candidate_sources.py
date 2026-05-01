"""One-shot validation of candidate default-source RSS URLs.

Mirrors the backend's `_build_custom_source_from_url` logic so the result
predicts what the production validate endpoint would do for each URL.

Run:
    python scripts/validate_candidate_sources.py
"""
from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import feedparser
import requests

CANDIDATES: dict[str, list[tuple[str, str]]] = {
    "News": [
        ("NPR News", "https://feeds.npr.org/1001/rss.xml"),
        ("Associated Press Top News", "https://feeds.apnews.com/rss/apf-topnews"),
        ("Axios", "https://api.axios.com/feed/"),
        ("BBC News", "https://feeds.bbci.co.uk/news/rss.xml"),
        ("Reuters Top News", "https://feeds.reuters.com/reuters/topNews"),
    ],
    "Politics": [
        ("Tangle", "https://www.readtangle.com/feed"),
        ("Heather Cox Richardson", "https://heathercoxrichardson.substack.com/feed"),
        ("Slow Boring", "https://www.slowboring.com/feed"),
        ("Politico Playbook", "https://rss.politico.com/playbook.xml"),
        ("The Bulwark", "https://www.thebulwark.com/feed"),
    ],
    "Business": [
        ("Lenny's Newsletter", "https://www.lennysnewsletter.com/feed"),
        ("Not Boring", "https://www.notboring.co/feed"),
        ("Marker (Medium)", "https://marker.medium.com/feed"),
        ("Axios Pro Rata", "https://api.axios.com/feed/pro-rata"),
        ("The Hustle", "https://thehustle.co/feed/"),
    ],
    "Tech": [
        ("Platformer", "https://www.platformer.news/feed"),
        ("Pragmatic Engineer", "https://newsletter.pragmaticengineer.com/feed"),
        ("Benedict Evans", "https://www.ben-evans.com/benedictevans?format=rss"),
        ("The Verge", "https://www.theverge.com/rss/index.xml"),
        ("Daring Fireball", "https://daringfireball.net/feeds/main"),
    ],
    "Strategy": [
        ("First Round Review", "https://review.firstround.com/rss"),
        ("Reforge", "https://www.reforge.com/blog/rss.xml"),
        ("a16z", "https://a16z.com/feed/"),
        ("Sequoia Perspectives", "https://www.sequoiacap.com/feed/"),
    ],
    "Personal Finance": [
        ("Of Dollars and Data", "https://ofdollarsanddata.com/feed/"),
        ("Mr. Money Mustache", "https://www.mrmoneymustache.com/feed/"),
        ("The Reformed Broker", "https://thereformedbroker.com/feed/"),
        ("Money with Katie", "https://moneywithkatie.com/feed"),
        ("A Wealth of Common Sense", "https://awealthofcommonsense.com/feed/"),
    ],
    "Science": [
        ("Astral Codex Ten", "https://www.astralcodexten.com/feed"),
        ("Quanta Magazine", "https://api.quantamagazine.org/feed/"),
        ("Scientific American", "https://www.scientificamerican.com/feed/"),
        ("Asimov Press", "https://press.asimov.com/feed"),
        ("Nautilus", "https://nautil.us/feed/"),
    ],
    "Sports": [
        ("Defector", "https://defector.com/feed"),
        ("The Ringer", "https://www.theringer.com/rss/index.xml"),
        ("JoeBlogs (Joe Posnanski)", "https://joeposnanski.substack.com/feed"),
        ("Sports Illustrated", "https://www.si.com/rss/si_topstories.rss"),
        ("ESPN Top Headlines", "https://www.espn.com/espn/rss/news"),
    ],
    "Culture": [
        ("Culture Study (Anne Helen Petersen)", "https://annehelen.substack.com/feed"),
        ("The Ankler", "https://theankler.com/feed"),
        ("Garbage Day", "https://www.garbageday.email/feed"),
        ("The New Yorker", "https://www.newyorker.com/feed/everything"),
        ("The Atlantic Culture", "https://www.theatlantic.com/feed/channel/entertainment/"),
    ],
    "Health & Wellness": [
        ("Peter Attia", "https://peterattiamd.com/feed/"),
        ("Examine", "https://examine.com/feeds/blog/"),
        ("Huberman Lab", "https://hubermanlab.com/feed/"),
        ("Outside Online", "https://www.outsideonline.com/rss"),
        ("NYT Well", "https://rss.nytimes.com/services/xml/rss/nyt/Well.xml"),
    ],
    "Food & Travel": [
        ("Eater", "https://www.eater.com/rss/index.xml"),
        ("Atlas Obscura", "https://www.atlasobscura.com/feeds/latest"),
        ("Stained Page News", "https://www.stainedpage.com/feed"),
        ("The Bittman Project", "https://www.bittmanproject.com/feed"),
        ("Serious Eats", "https://www.seriouseats.com/feed.xml"),
    ],
    "Romantasy": [
        ("Smart Bitches Trashy Books", "https://smartbitchestrashybooks.com/feed/"),
        ("Book Riot", "https://bookriot.com/feed/"),
        ("All About Romance", "https://allaboutromance.com/feed/"),
        ("Frolic", "https://frolic.media/feed/"),
        ("The Ripped Bodice", "https://www.therippedbodicela.com/blogs/news.atom"),
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
        # since some publishers (Reuters, Politico) 403 default-UA scrapers.
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
