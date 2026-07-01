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

    # Enforce the allowlist on MAIN-FRAME navigations only (page.goto,
    # link clicks, form posts that change the top-level URL). Playwright's
    # `is_navigation_request()` is True for iframe loads too — and Looker
    # legitimately embeds iframes from recaptcha, gapi-proxy hosts, etc.
    # `frame.parent_frame is None` is the main-frame test. Sub-resource
    # loads and iframe content aren't restricted; the goal is preventing
    # the SCRIPT from being driven somewhere unexpected, not firewalling
    # Google's CDN.
    def _block_disallowed(route, request):
        if (
            request.is_navigation_request()
            and request.frame.parent_frame is None
            and not _is_allowed(request.url)
        ):
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
    by `check` as the whole point.

    Looker has two domains in active use — `lookerstudio.google.com`
    (current) and `datastudio.google.com` (legacy redirect, still serves
    a marketing /overview page for unauthenticated visitors). The auth
    state is "are we looking at app chrome or marketing chrome", which
    we infer from the URL path."""
    page = context.pages[0] if context.pages else context.new_page()
    page.goto(LOOKER_HOME, wait_until="networkidle", timeout=45_000)
    final_url = page.url.lower()
    print(f"  landed at: {page.url}", file=sys.stderr)
    if "accounts.google.com" in final_url or "/signin" in final_url:
        return "signed-out"
    if "/overview" in final_url:
        # Marketing page — headless Chrome often lands here even with
        # valid cookies because Google's bot heuristics treat it as
        # untrusted. Headed mode usually passes through to the app.
        return "signed-out"
    if "lookerstudio.google.com" in final_url or "datastudio.google.com" in final_url:
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


# --- full-build automation (the brittle bit) -----------------------------
#
# Selectors are written against Looker Studio's UI as of 2026-05-26. If
# Google ships a redesign, expect breakage at the screenshotted step
# below. Each step is wrapped in `_step(...)` which catches the
# exception, dumps a screenshot to `.playwright-profile/last-error.png`,
# and re-raises with the step label so the operator knows where to
# resume from. `--start-at N` lets you re-run from a specific step
# without re-doing the work that's already on the report.

# The 4 views that are live today. The 2 commented-out lines need the
# Firestore export pipeline to materialize their source tables.
DASHBOARD_VIEWS: list[tuple[str, str, str]] = [
    # (data-source name, view name, suggested chart type)
    ("DAU / WAU / MAU",     "vw_dau_wau_mau",       "Time series chart"),
    ("Activation funnel",   "vw_activation_funnel", "Bar chart"),
    ("Cohort retention",    "vw_cohort_retention",  "Pivot table"),
    ("Episode completion",  "vw_episode_completion","Combo chart"),
    ("Activity & usage",    "vw_activity_windows",  "Table"),
    # ("Tier breakdown",    "vw_tier_breakdown",    "Table"),     # needs Firestore export
    # ("Churn-risk users",  "vw_churn_risk_users",  "Table"),     # needs Firestore export
]


class StepError(RuntimeError):
    """Raised when a build step fails. Carries the step label so the
    caller can print a resume hint without having to parse the message."""

    def __init__(self, label: str, original: Exception) -> None:
        super().__init__(f"{label}: {original}")
        self.label = label
        self.original = original


def _step(page, step_num: int, label: str, fn) -> None:
    """Wrap a build step. On failure, screenshot the page to the
    profile dir and re-raise as StepError with the step index so
    --start-at <n> can resume."""
    print(f"  [{step_num}] {label}...", file=sys.stderr)
    try:
        fn()
    except Exception as exc:
        screenshot = PROFILE_DIR / f"last-error-step-{step_num}.png"
        try:
            page.screenshot(path=str(screenshot), full_page=True)
            print(f"      screenshot: {screenshot}", file=sys.stderr)
        except Exception:
            pass
        raise StepError(f"step {step_num}: {label}", exc) from exc


def _click_first_match(page, selectors: list, timeout: int = 15_000) -> None:
    """Try a list of (kind, name) selectors and click the first one that
    appears. Lets us write fallbacks per step (aria-role first, then
    visible text, then a manual locator) without exploding the call
    site. `kind` is one of: 'role', 'text', 'locator'."""
    last_err: Exception | None = None
    for kind, value, *extra in selectors:
        try:
            if kind == "role":
                role, name = value, (extra[0] if extra else None)
                page.get_by_role(role, name=name).first.click(timeout=timeout)
            elif kind == "text":
                page.get_by_text(value, exact=(extra[0] if extra else False)).first.click(timeout=timeout)
            elif kind == "locator":
                page.locator(value).first.click(timeout=timeout)
            else:
                raise ValueError(f"unknown selector kind {kind!r}")
            return
        except Exception as exc:
            last_err = exc
            continue
    raise last_err or RuntimeError("no selectors provided to _click_first_match")


def _create_blank_report(page) -> None:
    """Click the home page 'Create' button and land in the editor.
    Modern Looker often skips the 'Blank report' submenu — the Create
    button goes straight to a new blank report. Detect both flows by
    checking whether the URL has moved to /reporting/.../edit; only
    click 'Blank report' if we haven't yet."""
    _click_first_match(page, [
        ("role", "button", "Create"),
        ("text", "Create", True),
    ])
    # Give Looker time to either open a submenu OR navigate to the editor.
    page.wait_for_timeout(1_500)
    if "/reporting/" in page.url and "/edit" in page.url:
        # Direct-to-editor flow; nothing more to click.
        return
    # Otherwise expect a submenu with "Blank report" / "Empty report".
    try:
        _click_first_match(page, [
            ("text", "Blank report"),
            ("text", "Empty report"),
        ], timeout=5_000)
        page.wait_for_timeout(3_000)
    except Exception:
        # Some flows go straight from Create to editor with no submenu;
        # if we're now in the editor, that's a success.
        if "/reporting/" in page.url and "/edit" in page.url:
            return
        raise


def _is_picker_already_open(page) -> bool:
    """Detect whether Looker's 'Add data to report' picker (the
    connector grid with BigQuery, Sheets, etc.) is already visible on
    screen. When yes, we skip the Resource → Manage flow and use the
    open picker directly."""
    try:
        # BigQuery card is visible on the picker; quick visibility probe.
        page.get_by_text("BigQuery", exact=True).first.wait_for(
            state="visible", timeout=1_500
        )
        return True
    except Exception:
        return False


def _close_add_data_dialog_if_present(page) -> None:
    """Tolerant dismissal of the 'Add data to report' dialog when we
    don't want to use it. Tries the X button (aria-label), text-button
    labels, and finally ESC. No-op if no dialog is open."""
    try:
        for selector in [
            "button[aria-label='Close']",
            "[role='dialog'] button[aria-label*='close' i]",
            "button[aria-label='Dismiss']",
        ]:
            try:
                page.locator(selector).first.click(timeout=1_500)
                return
            except Exception:
                continue
        for label in ("Cancel", "Close", "Skip", "Dismiss"):
            try:
                page.get_by_role("button", name=label).first.click(timeout=1_500)
                return
            except Exception:
                continue
        page.keyboard.press("Escape")
    except Exception:
        pass


def _add_bigquery_data_source(page, name: str, view: str) -> None:
    """Walk to the BigQuery custom-query flow and add a data source
    pointing at `analytics.<view>`. The most-repeated tedious flow in
    the whole dashboard build — automating just this saves the bulk
    of the click-time.

    Branch: if Looker's 'Add data to report' picker is already on
    screen (auto-opened after blank-report create, or left open from
    a previous add), reuse it. Otherwise open the picker via
    Resource → Manage added data sources → Add.
    """
    if not _is_picker_already_open(page):
        _click_first_match(page, [
            ("role", "menuitem", "Resource"),
            ("text", "Resource", True),
        ])
        page.wait_for_timeout(500)
        _click_first_match(page, [
            ("text", "Manage added data sources"),
            ("text", "Manage data sources"),
        ])
        page.wait_for_timeout(1_000)
        _click_first_match(page, [
            ("role", "button", "Add a data source"),
            ("text", "Add a data source"),
        ])
        page.wait_for_timeout(1_500)

    # BigQuery connector. There are many connectors; the search box
    # filters them.
    try:
        page.get_by_placeholder("Search").first.fill("BigQuery", timeout=5_000)
        page.wait_for_timeout(500)
    except Exception:
        pass
    _click_first_match(page, [
        ("text", "BigQuery", True),
        ("locator", "[aria-label*='BigQuery']"),
    ])
    page.wait_for_timeout(1_500)

    # Switch to Custom Query tab.
    _click_first_match(page, [
        ("text", "CUSTOM QUERY", False),
        ("text", "Custom query", False),
        ("text", "Custom Query", False),
    ])
    page.wait_for_timeout(500)

    # Pick the billing project. The project picker shows
    # "newsletter-pod" or your default project.
    try:
        _click_first_match(page, [
            ("text", "newsletter-pod", True),
        ], timeout=5_000)
    except Exception:
        # Sometimes the project is pre-selected; ignore.
        pass

    # Paste the SQL. The custom-query editor is a contenteditable or
    # ace-editor — try both.
    sql = f"SELECT * FROM `analytics.{view}`"
    pasted = False
    for selector in [
        "textarea[aria-label*='query']",
        "div[contenteditable='true']",
        "[role='textbox']",
        ".ace_text-input",
    ]:
        try:
            page.locator(selector).first.fill(sql, timeout=3_000)
            pasted = True
            break
        except Exception:
            continue
    if not pasted:
        raise RuntimeError("couldn't find the custom-query textbox")
    page.wait_for_timeout(500)

    # Click "Add" to register the data source.
    _click_first_match(page, [
        ("role", "button", "Add"),
    ])
    page.wait_for_timeout(2_000)

    # "Add to report" confirmation dialog.
    try:
        _click_first_match(page, [
            ("role", "button", "Add to report"),
        ], timeout=5_000)
        page.wait_for_timeout(1_500)
    except Exception:
        # Some flows skip the confirmation; ignore.
        pass


def cmd_build(args: argparse.Namespace) -> int:
    """Full automation: blank report → 4 BigQuery data sources →
    handoff. Stops short of actual tile config — that part of Looker's
    editor is too unstable to script reliably (different selectors per
    chart type, deeply nested dialogs)."""
    _ensure_playwright_installed()
    _ensure_chromium_installed()
    if not PROFILE_DIR.exists():
        print("no profile yet — run `login` first.", file=sys.stderr)
        return 1

    start_at = args.start_at
    report_id = args.report_id
    pw, context = _launch_persistent(headless=False)
    try:
        page = context.new_page()
        page.set_default_timeout(15_000)
        # Sequence each step with the wrapper so a failure prints a
        # screenshot path + the step number to resume from.
        steps: list[tuple[str, callable]] = []

        if report_id:
            # Resume on an existing report — skip Create flow entirely.
            edit_url = f"https://lookerstudio.google.com/reporting/{report_id}/edit"
            steps.append((f"Open existing report {report_id}", lambda: page.goto(
                edit_url, wait_until="domcontentloaded", timeout=45_000
            )))
            # Spacer so subsequent step numbers match the from-scratch flow,
            # keeping --start-at semantics stable.
            steps.append(("(skipped: Create + Blank report)", lambda: None))
        else:
            steps.append(("Open Looker Studio home", lambda: page.goto(
                LOOKER_HOME, wait_until="domcontentloaded", timeout=45_000
            )))
            steps.append(("Click 'Create' → 'Blank report'",
                          lambda: _create_blank_report(page)))

        for ds_name, view, _chart in DASHBOARD_VIEWS:
            label = f"Add data source: {ds_name} ({view})"
            steps.append((label, (lambda v=view, n=ds_name:
                                  _add_bigquery_data_source(page, n, v))))

        failed_step = None
        for i, (label, fn) in enumerate(steps, start=1):
            if i < start_at:
                print(f"  [{i}] skipping (start-at={start_at})", file=sys.stderr)
                continue
            try:
                _step(page, i, label, fn)
            except StepError as exc:
                failed_step = (i, exc)
                break

        if failed_step is not None:
            i, exc = failed_step
            print()
            print("=" * 64, file=sys.stderr)
            print(f"FAILED at {exc.label}", file=sys.stderr)
            print(f"  underlying: {exc.original}", file=sys.stderr)
            print(f"  fix the issue (or update the selector), then re-run:")
            print(f"  python scripts/looker/build_dashboard.py build --start-at {i}")
            print("=" * 64, file=sys.stderr)
            print("Window stays open so you can inspect the page state.")
            context.wait_for_event("close", timeout=0)
            return 1

        print()
        print("=" * 64)
        print(f"Added {len(DASHBOARD_VIEWS)} BigQuery data sources to the report.")
        print()
        print("Now do the visual tile config (Looker editor is too varied")
        print("to script reliably per chart type). For each data source,")
        print("Insert → <chart type> per docs/looker_studio_setup.md:")
        for ds_name, view, chart in DASHBOARD_VIEWS:
            print(f"  - {ds_name:<22} → {chart}")
        print()
        print("Then Share → schedule weekly to vincemartin1991@gmail.com.")
        print("Close the window when done.")
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
    build = sub.add_parser(
        "build",
        help="Full automation: create blank report + add the 4 BigQuery "
             "data sources. Stops at tile config (too varied per chart type).",
    )
    build.add_argument(
        "--start-at", type=int, default=1, metavar="N",
        help="Resume from step N (printed on failure). Default 1 = full run.",
    )
    build.add_argument(
        "--report-id", type=str, default=None, metavar="ID",
        help="Resume on an existing report (skip Create flow). "
             "ID is the UUID in the URL after /reporting/.",
    )
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
    if args.cmd == "build":
        return cmd_build(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
