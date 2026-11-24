#!/usr/bin/env python3
"""
Bump version script.

This script bumps the version in all files: VERSION, pyproject.toml files,
package.json, Chart.yaml appVersion, and .bumpversion.cfg.

Usage:
    python3 scripts/bump-version.py patch   # 0.0.3 -> 0.0.4
    python3 scripts/bump-version.py minor   # 0.0.3 -> 0.1.0
    python3 scripts/bump-version.py major   # 0.0.3 -> 1.0.0

This is used by the "Prepare Release" GitHub workflow.
"""
import re
import sys
import subprocess
from pathlib import Path

def bump_version(current: str, bump_type: str) -> str:
    """Calculate new version based on bump type."""
    major, minor, patch = map(int, current.split('.'))

    if bump_type == 'major':
        return f"{major + 1}.0.0"
    elif bump_type == 'minor':
        return f"{major}.{minor + 1}.0"
    elif bump_type == 'patch':
        return f"{major}.{minor}.{patch + 1}"
    else:
        raise ValueError(f"Invalid bump type: {bump_type}")

def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ['patch', 'minor', 'major']:
        print("Usage: bump-version.py [patch|minor|major]")
        sys.exit(1)

    bump_type = sys.argv[1]
    root_dir = Path(__file__).parent.parent
    version_file = root_dir / 'VERSION'

    # Read current version
    current_version = version_file.read_text().strip()
    print(f"Current version: {current_version}")

    # Calculate new version
    new_version = bump_version(current_version, bump_type)
    print(f"New version: {new_version} ({bump_type} bump)")

    # Update VERSION file
    version_file.write_text(f"{new_version}\n")
    print(f"✅ Updated VERSION file")

    # Update all pyproject.toml files
    pyproject_files = list(root_dir.glob('**/pyproject.toml'))
    pyproject_files = [f for f in pyproject_files if 'node_modules' not in str(f) and '.venv' not in str(f)]

    for pyproject in pyproject_files:
        content = pyproject.read_text()
        updated = re.sub(
            r'version = "[^"]*"',
            f'version = "{new_version}"',
            content,
            count=1
        )

        if updated != content:
            pyproject.write_text(updated)
            print(f"✅ Updated {pyproject.relative_to(root_dir)}")

    # Update package.json
    package_json = root_dir / 'agentarea-webapp' / 'package.json'
    if package_json.exists():
        content = package_json.read_text()
        updated = re.sub(
            r'"version":\s*"[^"]*"',
            f'"version": "{new_version}"',
            content,
            count=1
        )

        if updated != content:
            package_json.write_text(updated)
            print(f"✅ Updated {package_json.relative_to(root_dir)}")

    # Update .bumpversion.yaml
    bumpversion_yaml = root_dir / '.bumpversion.yaml'
    content = bumpversion_yaml.read_text()
    updated = re.sub(
        r'current_version:\s*.*',
        f'current_version: {new_version}',
        content
    )

    if updated != content:
        bumpversion_yaml.write_text(updated)
        print(f"✅ Updated .bumpversion.yaml")

    # Update Chart.yaml appVersion
    try:
        result = subprocess.run(
            [sys.executable, str(root_dir / 'scripts' / 'update-appversion.py')],
            capture_output=True,
            text=True,
            check=True
        )
        print(result.stdout.strip())
    except subprocess.CalledProcessError as e:
        print(f"⚠️  Warning: Failed to update Chart.yaml appVersion: {e.stderr}")

    # The committed OpenAPI specs carry the app version in info.version, and
    # the binary serves its copy of the webapp spec.
    openapi_specs = [
        root_dir / 'agentarea-webapp' / 'src' / 'api' / 'openapi.json',
        root_dir / 'docs' / 'api-reference' / 'openapi.json',
        root_dir / 'agentarea-platform' / 'api' / 'openapi' / 'openapi.json',
    ]

    for spec in openapi_specs:
        if spec.exists():
            content = spec.read_text()
            info = content.find('"info"')
            if info == -1:
                continue
            head, tail = content[:info], content[info:]
            updated = head + re.sub(
                r'"version":\s*"[^"]*"',
                f'"version": "{new_version}"',
                tail,
                count=1
            )

            if updated != content:
                spec.write_text(updated)
                print(f"✅ Updated {spec.relative_to(root_dir)}")

    # Refresh the fuzz project's uv.lock: it records the project's own version,
    # so bumping its pyproject alone leaves the lock behind and `uv sync
    # --locked` in CI refuses it.
    fuzz_dir = root_dir / 'agentarea-platform' / 'test' / 'fuzz'
    if (fuzz_dir / 'uv.lock').exists():
        try:
            subprocess.run(
                ['uv', 'lock'],
                cwd=fuzz_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            print("✅ Updated agentarea-platform/test/fuzz/uv.lock")
        except FileNotFoundError:
            sys.exit("❌ uv not found: agentarea-platform/test/fuzz/uv.lock cannot follow the bump")
        except subprocess.CalledProcessError as e:
            sys.exit(f"❌ Failed to refresh agentarea-platform/test/fuzz/uv.lock: {e.stderr}")

    print(f"\n✅ All versions bumped to {new_version}")

if __name__ == '__main__':
    main()
