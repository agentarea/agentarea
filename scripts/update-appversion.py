#!/usr/bin/env python3
"""
Update appVersion in Chart.yaml to match the VERSION file.
This keeps the application version synchronized while allowing
the chart version to be managed independently.
"""
import re
import sys
from pathlib import Path

def update_chart_appversion(chart_path):
    """Update appVersion to match VERSION file (not chart version)"""
    # Read application version from VERSION file (single source of truth)
    version_file = Path(__file__).parent.parent / 'VERSION'
    if not version_file.exists():
        print(f"Error: VERSION file not found at {version_file}")
        sys.exit(1)

    app_version = version_file.read_text().strip()
    if not app_version:
        print("Error: VERSION file is empty")
        sys.exit(1)

    # Update Chart.yaml appVersion field
    with open(chart_path, 'r') as f:
        content = f.read()

    # Update ONLY appVersion field (not version field)
    # Chart version is managed independently
    updated_content = re.sub(
        r'appVersion:\s+"[^"]+"',
        f'appVersion: "{app_version}"',
        content
    )

    if updated_content == content:
        print(f"✅ Chart appVersion already set to {app_version}")
        return

    with open(chart_path, 'w') as f:
        f.write(updated_content)

    print(f"✅ Updated Chart appVersion to {app_version} (chart version unchanged)")

if __name__ == '__main__':
    update_chart_appversion('charts/agentarea/Chart.yaml')
