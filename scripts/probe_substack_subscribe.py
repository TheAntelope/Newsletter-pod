"""Probe Substack's undocumented free-subscribe endpoint.

** RESULT (2026-05-13): DEAD END. **
The endpoint is now JS-gated. POSTing as below returns:
  HTTP 400 {"error":"Please enable JavaScript to subscribe to this newsletter.","type":"single"}
even with a cookie warm-up from /subscribe. The older reverse-engineering
writeups that documented `?nojs=true` predate this change. To bypass would
require a headless browser submitting the real form (Playwright/Puppeteer)
or solving Substack's JS-side challenge token. We chose not to go down
either path -- see the per-publication deep-link UX shipped instead
(/v1/me/substack/intents + iOS "Add a Substack" sheet).

Kept here as documentation of the spike + a starting point if Substack
ever reverses the gating. Re-run with:
    python scripts/probe_substack_subscribe.py \\
        --pub https://heathercoxrichardson.substack.com \\
        --email sdke2jm@theclawcast.com
"""
from __future__ import annotations

import argparse
import sys
from urllib.parse import urlparse

import requests

DEFAULT_PUB = "https://heathercoxrichardson.substack.com"
DEFAULT_EMAIL = "sdke2jm@theclawcast.com"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def probe(pub_url: str, email: str) -> int:
    pub_url = pub_url.rstrip("/")
    host = urlparse(pub_url).netloc
    if not host:
        print(f"Invalid pub URL: {pub_url}", file=sys.stderr)
        return 2

    endpoint = f"{pub_url}/api/v1/free?nojs=true"
    headers = {
        "User-Agent": UA,
        "Origin": pub_url,
        "Referer": f"{pub_url}/subscribe",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
    }
    body = {"email": email, "source": "subscribe_page"}

    session = requests.Session()

    # Warm up: GET the subscribe page so Cloudflare/Substack issue us their
    # bot-management + experiment cookies before we POST.
    warmup_url = f"{pub_url}/subscribe"
    print(f"GET (warm-up) {warmup_url}")
    warmup = session.get(
        warmup_url,
        headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"},
        timeout=15,
    )
    print(f"  status={warmup.status_code}  cookies={[c.name for c in session.cookies]}")
    print()

    print(f"POST {endpoint}")
    print(f"  email={email}")
    print(f"  origin={pub_url}")
    print()

    resp = session.post(endpoint, headers=headers, data=body, timeout=15)

    print(f"Status: {resp.status_code}")
    print("Response headers:")
    for k, v in resp.headers.items():
        print(f"  {k}: {v}")
    print()
    print("Body (first 2KB):")
    print(resp.text[:2048])

    return 0 if resp.ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pub", default=DEFAULT_PUB, help="Publication root URL")
    parser.add_argument("--email", default=DEFAULT_EMAIL, help="Recipient email")
    args = parser.parse_args()
    return probe(args.pub, args.email)


if __name__ == "__main__":
    sys.exit(main())
