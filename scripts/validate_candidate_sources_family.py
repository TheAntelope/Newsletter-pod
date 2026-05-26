"""Validate Family Life candidate RSS feeds before adding to defaults.

Mix of fatherhood-leaning, motherhood-leaning, and neutral parenting
sources for a new top-level Family Life category.
"""
from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import feedparser
import requests

CANDIDATES: dict[str, list[tuple[str, str]]] = {
    "Family Life (new category)": [
        # Fatherhood-leaning
        ("Fatherly", "https://www.fatherly.com/feed/"),
        ("Dad Suggests", "https://www.dadsuggests.com/rss"),
        ("Art of Manliness", "https://www.artofmanliness.com/feed/"),
        # Motherhood-leaning
        ("Motherly", "https://www.mother.ly/feed"),
        ("Cup of Jo", "https://cupofjo.com/feed/"),
        ("Scary Mommy", "https://www.scarymommy.com/feed"),
        ("Romper", "https://www.romper.com/rss"),
        ("Today's Parent", "https://www.todaysparent.com/feed/"),
        # Neutral / evidence-based
        ("ParentData (Emily Oster)", "https://emilyoster.substack.com/feed"),
        ("The Atlantic Family", "https://www.theatlantic.com/feed/channel/family/"),
        ("NYT Parenting", "https://rss.nytimes.com/services/xml/rss/nyt/Parenting.xml"),
        ("Burnt Toast (Virginia Sole-Smith)", "https://virginiasolesmith.substack.com/feed"),
        ("Janet Lansbury", "https://www.janetlansbury.com/feed/"),
        ("Let Grow (Free Range Kids)", "https://www.letgrow.org/feed/"),
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
