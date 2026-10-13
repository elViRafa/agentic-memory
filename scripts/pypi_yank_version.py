#!/usr/bin/env python3
"""Yank a memory-fabric release on PyPI (requires a project API token).

Usage:
  PYPI_API_TOKEN=... python scripts/pypi_yank_version.py 1.4.3
  PYPI_API_TOKEN=... python scripts/pypi_yank_version.py 1.4.3 --reason "superseded by 1.4.4"

Token: https://pypi.org/manage/account/token/ with scope for project memory-fabric.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def main() -> int:
    parser = argparse.ArgumentParser(description="Yank a memory-fabric version on PyPI")
    parser.add_argument("version", help="Version to yank, e.g. 1.4.3")
    parser.add_argument(
        "--reason",
        default="Superseded; install memory-fabric>=1.4.4 instead.",
        help="Yank reason shown on PyPI",
    )
    args = parser.parse_args()
    token = os.environ.get("PYPI_API_TOKEN") or os.environ.get("TWINE_PASSWORD")
    if not token:
        print("Set PYPI_API_TOKEN (or TWINE_PASSWORD) to a PyPI API token.", file=sys.stderr)
        return 1

    url = f"https://pypi.org/pypi/memory-fabric/{args.version}/yank"
    body = json.dumps({"reason": args.reason}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            print(resp.read().decode("utf-8") or "ok")
    except urllib.error.HTTPError as exc:
        print(exc.read().decode("utf-8", errors="replace"), file=sys.stderr)
        return exc.code if exc.code else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
