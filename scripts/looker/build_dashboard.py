"""Narrow-scoped browser automation for the ClawCast Looker Studio dashboard.

Why this exists: Looker Studio has no programmatic API for creating
reports. The 6-tile dashboard documented in `docs/looker_studio_setup.md`
is a 20-minute manual click-through. This script automates the painful
half (Google login + repeated boilerplate) and hands off to you for the
parts that are faster done by hand (visual tile config).

Design constraints, deliberately:

* **Repo-scoped Chrome profile.** Stored under `./.playwright-profile/`
  (gitignored). First run: you log in once in a headed browser. Every
  later run reuses the saved Google session, no password re-entry, no
  2FA prompts (beyond Google's normal session-lifetime).
* **Tiny URL allowlist.** Navigation outside the documented hosts is
  blocked at the route layer. The browser literally cannot, e.g.,
  click into App Store Connect or modify your GitHub account. The
  blast radius is "things you can do inside Looker Studio".
* **Headed by default.** You watch every click. `--headless` exists
  but is opt-in. The point of headed mode is so a misclick or a
  Looker-UI redesign is visible immediately, not silently broken.
* **No selectors-rich automation past the create-report screen.** The
  Looker tile editor is unstable Material-Design with deeply nested
  shadow roots — automating it is high-maintenance and low value
  (since you only build the dashboard once). This script does the
  boilerplate (login, profile, create-report, open the right URL)
  and stops there.

Usage:

  # 1. One-time install (in the project venv)
  pip install -e .[browser]
  playwright install chromium

  # 2. First-run: log in to Google. Browser stays open until you close it.
  python scripts/looker/build_dashboard.py login

  # 3. Verify the session is alive (no UI, just check Looker loads
  #    while signed in)
  python scripts/looker/build_dashboard.py check

  # 4. Open Looker Studio at the report list (you click "Create" yourself).
  python scripts/looker/build_dashboard.py open

  # 5. Drive the "Create new blank report" boilerplate. Stops once
  #    you're in the editor; you add the 6 BigQuery data sources +
  #    tiles per docs/looker_studio_setup.md.
  python scripts/looker/build_dashboard.py create-report

Anything fancier (tile templating, dashboard cloning) — file an issue
and we extend. Don't bolt on tile-level selectors here without a
maintenance plan; Looker UI churn is real.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROFILE_DIR = REPO_ROOT / ".playwright-profile"
LOOKER_HOME = "https://lookerstudio.google.com/"
LOOKER_CREATE_BLANK = "https://lookerstudio.google.com/reporting/create?c.reportId=&r.measurementId="

# Hosts the browser is allowed to *navigate* to (page.goto / click-through
# nav). Sub-resource loads (fonts, images, XHR) aren't restricted — the
# point is to prevent the browser from being driven into surprising
# territory, not to firewall Google's CDN. Match by suffix so subdomain
# variations of these load.
NAV_ALLOWLIST = frozenset({
    "lookerstudio.google.com",
    "accounts.google.com",
    "accounts.youtube.com",         # Google login redirect on some flows
    "myaccount.google.com",         # Lands here after some account changes
    "ssl.gstatic.com",
    "fonts.gstatic.com",
    "apis.google.com",
    "ogs.google.com",               # Google sign-in toolbar
    "drive.google.com",             # Looker stores reports in Drive
    "datastudio.google.com",        # Legacy redirect to Looker Studio
    "policies.google.com",          # Terms / privacy popups
})


def _is_allowed(url: str) -> bool:
    """Suffix-match the URL's host against NAV_ALLOWLIST. Google's CDNs
    use many `*.googleusercontent.com` and `*.gstatic.com` subdomains;
    we allow the documented hosts and treat anything else as
    out-of-scope."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    if not host:
        return False
    if host in NAV_ALLOWLIST:
        return True
    # Allow googleusercontent / gstatic subdomains (avatars, assets).
    if host.endswith(".googleusercontent.com"):
        return True
    if host.endswith(".gstatic.com"):
        return True
    return False


def _ensure_playwright_installed() -> None:
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        sys.stderr.write(
            "Playwright isn't installed. From the project venv:\n"
            "  pip install -e .[browser]\n"
            "  playwright install chromium\n"
        )
        sys.exit(2)


def _ensure_chromium_installed() -> None:
    from playwright.sync_api import sync_playwright
    from playwright._impl._errors import Error as PWError

    with sync_playwright() as p:
        try:
            # Browser executable presence is checked lazily; a missing
            # binary throws at launch_persistent_context, not here. So
            # we do a no-op launch in a fresh tempdir to probe.
            import tempfile
            with tempfile.TemporaryDirectory() as tmp:
                ctx = p.chromium.launch_persistent_context(
                    tmp, headless=True
                )
                ctx.close()
        except PWError as exc:
            if "Executable doesn't exist" in str(exc):
                sys.stderr.write(
                    "Chromium isn't installed for Playwright. Run:\n"
                    "  playwright install chromium\n"
                )
                sys.exit(2)
            raise


def _launch_persistent(headless: bool):
    """Open the persistent-profile Chromium context with the URL
    allowlist enforced at navigation time. Returns the BrowserContext
    so the caller can hand-roll the rest of the flow."""
    from playwright.sync_api import sync_playwright

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    pw = sync_playwright().start()
    context = pw.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=headless,
        # Mitigate the most obvious "I'm a bot" signal — without it,
        # Google's anti-automation heuristics flag the session and the
        # login fails with "couldn't sign you in".
        args=["--disable-blink-features=AutomationControlled"],
        viewport={"width": 1440, "height": 900},
    )

    # Enforce the allowlist on every navigation attempt (page.goto,
    # link clicks, form posts that change the top-level URL). Resource
    # loads inside an allowed page are not blocked — that would break
    # most of Google's UI.
    def _block_disallowed(route, request):
        if request.is_navigation_request() and not _is_allowed(request.url):
            print(f"  blocked navigation to {request.url}", file=sys.stderr)
            route.abort()
        else:
            route.continue_()

    for page in context.pages:
        page.route("**/*", _block_disallowed)
    context.on("page", lambda page: page.route("**/*", _block_disallowed))

    return pw, context


def _print_session_status(context) -> str:
    """Probe Looker Studio's home page; return 'signed-in', 'signed-out',
    or 'unreachable'. Used by `login` to know when to stop blocking and
    by `check` as the whole point."""
    page = context.pages[0] if context.pages else context.new_page()
    page.goto(LOOKER_HOME, wait_until="networkidle", timeout=45_000)
    # When signed in, Looker shows the reports grid with a "Create" CTA.
    # When signed out it redirects to accounts.google.com and the URL
    # changes. That's the cheapest tell.
    final_url = page.url
    if "accounts.google.com" in final_url:
        return "signed-out"
    if "lookerstudio.google.com" in final_url:
        return "signed-in"
    return "unreachable"


# --- subcommands ----------------------------------------------------------


def cmd_login(args: argparse.Namespace) -> int:
    """Open a headed Chromium pinned at the profile dir, navigate to
    Looker Studio, and wait for you to sign in. Closes when you close
    the window. Subsequent runs of `check` / `open` / `create-report`
    reuse the saved cookies."""
    _ensure_playwright_installed()
    _ensure_chromium_installed()
    pw, context = _launch_persistent(headless=False)
    try:
        page = context.new_page()
        print(f"profile: {PROFILE_DIR}")
        print("opening Looker Studio — sign in to Google when prompted.")
        print("when you're back at the Looker home page, close the window")
        print("to save the session.")
        page.goto(LOOKER_HOME, wait_until="domcontentloaded", timeout=45_000)
        # Wait for the user to close the window — that's the signal that
        # they're done. context.wait_for_event('close') is the idiomatic
        # way to block until the user closes Chromium.
        context.wait_for_event("close", timeout=0)
        print("session saved to", PROFILE_DIR)
        return 0
    finally:
        try:
            context.close()
        except Exception:
            pass
        pw.stop()


def cmd_check(args: argparse.Namespace) -> int:
    """Headless probe: is the saved session still alive? Returns
    exit-0 when signed in, exit-1 when signed out (so CI can chain on
    it later if we ever automate the dashboard rebuild on a schedule)."""
    _ensure_playwright_installed()
    _ensure_chromium_installed()
    if not PROFILE_DIR.exists():
        print("no profile yet — run `login` first.", file=sys.stderr)
        return 1
    pw, context = _launch_persistent(headless=True)
    try:
        status = _print_session_status(context)
        print(status)
        return 0 if status == "signed-in" else 1
    finally:
        context.close()
        pw.stop()


def cmd_open(args: argparse.Namespace) -> int:
    """Headed launch at the Looker Studio home page. You drive from
    here. Useful for manual click-through with the persistent session
    already attached (so no re-login dance)."""
    _ensure_playwright_installed()
    _ensure_chromium_installed()
    pw, context = _launch_persistent(headless=False)
    try:
        page = context.new_page()
        page.goto(LOOKER_HOME, wait_until="domcontentloaded", timeout=45_000)
        print("Looker Studio open. Close the window when done.")
        context.wait_for_event("close", timeout=0)
        return 0
    finally:
        try:
            context.close()
        except Exception:
            pass
        pw.stop()


def cmd_create_report(args: argparse.Namespace) -> int:
    """Open Looker Studio at the 'create blank report' URL. From there
    you add data sources + tiles per docs/looker_studio_setup.md.

    Deliberately does NOT try to script the tile config — Looker's
    visual editor is a Material-Design rats-nest of dialogs and
    iframes that drift between releases. The few minutes saved by
    automating tile creation are paid back many times over the first
    time a selector silently breaks.
    """
    _ensure_playwright_installed()
    _ensure_chromium_installed()
    if not PROFILE_DIR.exists():
        print("no profile yet — run `login` first.", file=sys.stderr)
        return 1
    pw, context = _launch_persistent(headless=False)
    try:
        page = context.new_page()
        # Looker has changed the "create report" URL a couple of times;
        # the home page is the safest entry. From there we click the
        # Create button via aria-label.
        page.goto(LOOKER_HOME, wait_until="domcontentloaded", timeout=45_000)
        if "accounts.google.com" in page.url:
            print("session expired — re-run `login`.", file=sys.stderr)
            return 1

        # The "Create" button on the home page. aria-label is the most
        # stable hook; if Google removes it, fall back to button text.
        try:
            page.get_by_role("button", name="Create").first.click(timeout=15_000)
        except Exception:
            try:
                page.get_by_text("Create", exact=True).first.click(timeout=10_000)
            except Exception as exc:
                print(
                    "couldn't find the 'Create' button — Looker UI may have "
                    f"changed. {exc}",
                    file=sys.stderr,
                )
                print("falling back: navigating directly to a blank report.")
                page.goto(LOOKER_CREATE_BLANK, wait_until="domcontentloaded")

        print()
        print("=" * 64)
        print("Looker Studio is open at the 'New report' flow.")
        print()
        print("Next steps (per docs/looker_studio_setup.md):")
        print("  1. Close the 'Add data' dialog if it pops up.")
        print("  2. File → Report settings → Date range: Last 28 days.")
        print("  3. Resource → Manage added data sources → Add a data")
        print("     source → BigQuery → Custom query. Repeat 6 times,")
        print("     one for each `vw_*` view (paste the wrapper from")
        print("     the doc table).")
        print("  4. Insert each of the 6 tiles per the doc.")
        print("  5. Share → restricted, anyone with access can view.")
        print("  6. Schedule weekly email to vincemartin1991@gmail.com.")
        print()
        print("Close the window when done — the session stays saved.")
        print("=" * 64)
        context.wait_for_event("close", timeout=0)
        return 0
    finally:
        try:
            context.close()
        except Exception:
            pass
        pw.stop()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="build_dashboard.py",
        description="Narrow Looker Studio browser automation. "
                    "Auth helper + create-report boilerplate. "
                    "Tile config stays manual on purpose.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("login", help="One-time: sign in to Google in a headed browser.")
    sub.add_parser("check", help="Headless probe of the saved session.")
    sub.add_parser("open", help="Open Looker Studio home with the saved session.")
    sub.add_parser("create-report", help="Open the new-report editor; manual tile config from there.")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    if args.cmd == "login":
        return cmd_login(args)
    if args.cmd == "check":
        return cmd_check(args)
    if args.cmd == "open":
        return cmd_open(args)
    if args.cmd == "create-report":
        return cmd_create_report(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
