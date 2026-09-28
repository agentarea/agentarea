#!/usr/bin/env python3
"""Bump the chart version of every chart the release publishes.

Chart versions are the release workflow's to move, never a reviewer's, so this
script owns all of them rather than one. It discovers them instead of listing
them: a chart added under charts/ used to be packaged and published while its
version sat still, which meant a later release replaced an existing version with
different content, and anyone who had pinned that version silently resolved a
chart they had never seen.

Only top-level charts are ours. A vendored subchart under charts/*/charts/ keeps
its upstream version, and a dependency helm fetches is not in git at all.

appVersion is a separate contract, tracked against the VERSION file by
scripts/update-appversion.py; this script does not touch it.

Usage:
    python3 scripts/bump-chart-version.py patch   # 0.0.3 -> 0.0.4
    python3 scripts/bump-chart-version.py minor   # 0.0.3 -> 0.1.0
    python3 scripts/bump-chart-version.py major   # 0.0.3 -> 1.0.0
"""

import re
import sys
from pathlib import Path

CHARTS_DIR = Path(__file__).parent.parent / "charts"

VERSION_LINE = re.compile(r"^version:\s+(\S+)", re.MULTILINE)


def bump(version: str, part: str) -> str:
    major, minor, patch = map(int, version.split("."))
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def published_charts() -> list[Path]:
    """Every top-level chart, sorted so the output is stable."""
    return sorted(CHARTS_DIR.glob("*/Chart.yaml"))


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in ("patch", "minor", "major"):
        print("Usage: bump-chart-version.py [patch|minor|major]", file=sys.stderr)
        return 1

    part = sys.argv[1]
    charts = published_charts()
    if not charts:
        print(f"No charts found under {CHARTS_DIR}", file=sys.stderr)
        return 1

    for chart in charts:
        content = chart.read_text()
        match = VERSION_LINE.search(content)
        if not match:
            print(f"No 'version:' field in {chart}", file=sys.stderr)
            return 1

        current = match.group(1)
        try:
            new_version = bump(current, part)
        except ValueError:
            print(f"{chart}: version {current!r} is not major.minor.patch", file=sys.stderr)
            return 1

        chart.write_text(VERSION_LINE.sub(f"version: {new_version}", content, count=1))
        print(f"{chart.parent.name}: {current} -> {new_version}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
