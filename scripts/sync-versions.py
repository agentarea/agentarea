#!/usr/bin/env python3
"""
Emergency version synchronization script.

This script syncs all version files to match the VERSION file.

⚠️  USE WITH CAUTION: This bypasses the normal bumpversion workflow.

When to use:
- Emergency recovery when versions are badly out of sync
- After manual VERSION file edits (not recommended)
- Troubleshooting version drift issues

Normal workflow: Use the "Prepare Release" GitHub workflow instead.
"""
import re
from pathlib import Path

def main():
    # Read target version from VERSION file
    version_file = Path(__file__).parent.parent / 'VERSION'
    target_version = version_file.read_text().strip()
    print(f"Target version: {target_version}")

    # Update all pyproject.toml files
    pyproject_files = list(Path(__file__).parent.parent.glob('**/pyproject.toml'))
    # Exclude node_modules and .venv
    pyproject_files = [f for f in pyproject_files if 'node_modules' not in str(f) and '.venv' not in str(f)]

    for pyproject in pyproject_files:
        with open(pyproject, 'r') as f:
            content = f.read()

        updated = re.sub(
            r'version = "[^"]*"',
            f'version = "{target_version}"',
            content,
            count=1  # Only update the first occurrence
        )

        if updated != content:
            with open(pyproject, 'w') as f:
                f.write(updated)
            print(f"✅ Updated {pyproject.relative_to(Path.cwd())}")

    # Update package.json
    package_json = Path(__file__).parent.parent / 'agentarea-webapp' / 'package.json'
    if package_json.exists():
        with open(package_json, 'r') as f:
            content = f.read()

        updated = re.sub(
            r'"version":\s*"[^"]*"',
            f'"version": "{target_version}"',
            content,
            count=1
        )

        if updated != content:
            with open(package_json, 'w') as f:
                f.write(updated)
            print(f"✅ Updated {package_json.relative_to(Path.cwd())}")

    # Update .bumpversion.cfg current_version
    bumpversion_cfg = Path(__file__).parent.parent / '.bumpversion.cfg'
    with open(bumpversion_cfg, 'r') as f:
        content = f.read()

    updated = re.sub(
        r'current_version = .*',
        f'current_version = {target_version}',
        content
    )

    if updated != content:
        with open(bumpversion_cfg, 'w') as f:
            f.write(updated)
        print(f"✅ Updated {bumpversion_cfg.relative_to(Path.cwd())}")

    print(f"\n✅ All versions synchronized to {target_version}")

if __name__ == '__main__':
    main()
