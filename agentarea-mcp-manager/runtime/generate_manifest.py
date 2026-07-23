"""Emit the runtime capability manifest for the sandbox image.

Runs at image build time; the output is baked into /etc/agentarea/runtime.json
and served by the activation service at GET /runtime/manifest. The manifest is
the single source of truth the platform uses to tell agents what this runtime
can and cannot do — never hand-edit the JSON, change this script or
requirements.txt instead.
"""

import json
import os
import platform
import subprocess
import sys
from importlib import metadata
from typing import Literal


def command_version(*command: str) -> str:
    out = subprocess.run(command, capture_output=True, text=True, check=True)
    return out.stdout.strip()


def installed_packages() -> dict[str, str]:
    return dict(
        sorted((dist.metadata["Name"], dist.version) for dist in metadata.distributions())
    )


def main() -> None:
    version = os.environ.get("RUNTIME_VERSION")
    if not version:
        raise SystemExit("RUNTIME_VERSION must be set at build time")
    managed_environment: Literal["mutable", "immutable"] | str = os.environ.get(
        "MANAGED_ENVIRONMENT", "mutable"
    )
    if managed_environment not in {"mutable", "immutable"}:
        raise SystemExit("MANAGED_ENVIRONMENT must be mutable or immutable")

    manifest = {
        "schema_version": 1,
        "image_version": version,
        "managed_environment": managed_environment,
        "python": {
            "version": platform.python_version(),
            "executable": sys.executable,
        },
        "node": {
            "version": command_version("node", "--version"),
            "npm_version": (
                command_version("npm", "--version")
                if managed_environment == "mutable"
                else ""
            ),
        },
        "tools": {
            "curl": command_version("curl", "--version").splitlines()[0],
            "git": command_version("git", "--version"),
            "jq": command_version("jq", "--version"),
        },
        "packages": installed_packages(),
        "features": {
            "browser": "none",
            "managed_environment_mutation": managed_environment == "mutable",
            "arbitrary_workspace_code": True,
        },
    }
    json.dump(manifest, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
