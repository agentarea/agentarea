#!/usr/bin/env python3
"""Bump chart version in Chart.yaml independently from app version.

Usage:
    python3 scripts/bump-chart-version.py patch   # 0.0.3 -> 0.0.4
    python3 scripts/bump-chart-version.py minor   # 0.0.3 -> 0.1.0
    python3 scripts/bump-chart-version.py major   # 0.0.3 -> 1.0.0
"""
import re
import sys
from pathlib import Path

CHART_PATH = Path(__file__).parent.parent / 'charts/agentarea/Chart.yaml'


def bump(version: str, part: str) -> str:
    major, minor, patch = map(int, version.split('.'))
    if part == 'major':
        return f"{major + 1}.0.0"
    if part == 'minor':
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


if __name__ == '__main__':
    if len(sys.argv) < 2 or sys.argv[1] not in ('patch', 'minor', 'major'):
        print("Usage: bump-chart-version.py [patch|minor|major]")
        sys.exit(1)

    part = sys.argv[1]
    content = CHART_PATH.read_text()
    match = re.search(r'^version:\s+(\S+)', content, re.MULTILINE)
    if not match:
        print("❌ Could not find 'version:' field in Chart.yaml")
        sys.exit(1)

    current = match.group(1)
    new_version = bump(current, part)
    updated = re.sub(r'^version:\s+\S+', f'version: {new_version}', content, flags=re.MULTILINE)
    CHART_PATH.write_text(updated)
    print(f"✅ Bumped chart version: {current} → {new_version}")
