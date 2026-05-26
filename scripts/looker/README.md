# Looker Studio dashboard automation

Narrow-scoped Playwright tool for the ClawCast analytics dashboard.

## What it does and doesn't do

**Does:**
- Persists a Google session in a local Chrome profile so you log in
  exactly once.
- Opens Looker Studio with that session pre-attached — no re-auth dance.
- Walks you to the "New report" flow with a printed checklist of what
  to click next.
- Enforces a navigation allowlist (only Google's auth + Looker hosts
  can become the top-level URL).

**Does not:**
- Try to script the 6-tile config. Looker's visual editor is a
  Material-Design / iframe maze that changes between releases. Manual
  click-through per [docs/looker_studio_setup.md](../../docs/looker_studio_setup.md)
  is 20 minutes you do once; a script for it would be 600 lines that
  break every few months.
- Touch any host outside Google's Looker/auth surface. The browser
  literally cannot be driven into App Store Connect, GCP console,
  GitHub, etc.

## Setup (once per machine)

```powershell
# From the repo root in your project venv:
pip install -e .[browser]
playwright install chromium    # ~150MB download
```

## Use

```powershell
# 1. Sign in once. Real headed Chromium opens; sign in with your
#    Google account that has BigQuery + Looker access. The browser
#    stays open until you close it.
.venv\Scripts\python.exe scripts\looker\build_dashboard.py login

# 2. Re-check the session whenever (headless, no UI). Exits 0 when
#    signed in, 1 when expired.
.venv\Scripts\python.exe scripts\looker\build_dashboard.py check

# 3. When you want to build the dashboard:
.venv\Scripts\python.exe scripts\looker\build_dashboard.py create-report
#    Opens Looker Studio at the new-report flow with the printed
#    next-step checklist. Add data sources + tiles per
#    docs/looker_studio_setup.md.

# 4. For any other Looker work in the same authed session:
.venv\Scripts\python.exe scripts\looker\build_dashboard.py open
```

## Where the session lives

`.playwright-profile/` at the repo root. Gitignored. Holds Google
session cookies for whichever account you logged in as. To force a
re-login (e.g. switching accounts), delete the directory:

```powershell
Remove-Item -Recurse -Force .playwright-profile
```

## Security model

- The profile dir is on your machine only, never committed, never
  uploaded.
- The navigation allowlist blocks `page.goto()` / form submits to
  any host not in `NAV_ALLOWLIST` inside
  `scripts/looker/build_dashboard.py`. Resource loads (CSS, fonts,
  XHR) inside an allowed page are NOT blocked — otherwise Google's
  UI breaks immediately.
- Headed by default. `--headless` exists for the `check` subcommand
  but every interactive subcommand runs visibly so a UI drift or
  surprise dialog is observable.
- The tool only does what the subcommands name. There's no
  `do-anything` mode. Extending it means adding a named subcommand
  with a documented scope.

## Extending

Sensible additions (file an issue first):

- A `clone-from-template` subcommand if Google ever ships a stable
  Looker Studio templating URL.
- A `verify-dashboard` subcommand that opens the dashboard and
  screenshots each tile, for visual-regression review after a
  Looker UI redesign.

Bad additions:

- Tile-by-tile automation in the visual editor. Don't.
- Adding hosts to `NAV_ALLOWLIST` casually — every host added
  widens the blast radius.
