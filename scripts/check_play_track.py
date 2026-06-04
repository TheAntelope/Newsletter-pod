#!/usr/bin/env python3
"""Print the live release state of a Google Play track (read-only).

Wraps `google-play tracks get` (codemagic-cli-tools) so a Codemagic build —
or anyone with the Play Developer service account — can confirm which
versionCode is actually live to testers, and its rollout status, without
clicking through the Play Console.

Credentials: reads the same service-account JSON the Codemagic `google_play`
variable group exposes as GCLOUD_SERVICE_ACCOUNT_CREDENTIALS. Pass an explicit
path/JSON with --credentials to run locally.

Usage:
    python scripts/check_play_track.py [--track internal] [--package-name com.newsletterpod.app]

Exit code is 0 even when the track has no releases yet (first upload still
processing) — this is a reporting tool, not a gate. It exits non-zero only if
the API call itself fails (bad/expired credentials, network, wrong package).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--package-name", default=os.environ.get("PACKAGE_NAME", "com.newsletterpod.app"))
    ap.add_argument("--track", default="internal")
    ap.add_argument(
        "--credentials",
        default="@env:GCLOUD_SERVICE_ACCOUNT_CREDENTIALS",
        help="Service-account JSON, or @env:VAR / @file:PATH (codemagic-cli-tools syntax).",
    )
    args = ap.parse_args()

    cmd = [
        "google-play", "tracks", "get",
        "--package-name", args.package_name,
        "--track", args.track,
        "--credentials", args.credentials,
        "--json",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(
            f"ERROR: `google-play tracks get` failed (exit {proc.returncode}).\n{proc.stderr}\n"
        )
        return proc.returncode or 1

    try:
        track = json.loads(proc.stdout)
    except json.JSONDecodeError:
        # Older CLI versions print plain text; just echo it through.
        print(proc.stdout.strip())
        return 0

    releases = track.get("releases") or []
    print(f"=== Google Play '{args.track}' track for {args.package_name} ===")
    if not releases:
        print("(no releases on this track yet — a fresh upload may still be processing)")
        return 0

    for r in releases:
        # status: 'completed' = live to all on the track; 'inProgress' = staged
        # rollout; 'draft' = uploaded but not released; 'halted' = stopped.
        codes = ", ".join(str(c) for c in (r.get("versionCodes") or []))
        status = r.get("status", "?")
        name = r.get("name", "")
        frac = r.get("userFraction")
        line = f"  versionCode(s) {codes}: status={status}"
        if name:
            line += f"  name={name}"
        if frac is not None:
            line += f"  rollout={frac}"
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
