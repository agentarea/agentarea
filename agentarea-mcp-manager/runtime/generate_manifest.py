"""Emit the runtime capability manifest for the sandbox image.

Runs at image build time; the output is baked into /etc/agentarea/runtime.json
and served by the activation service at GET /runtime/manifest. The manifest is
the single source of truth the platform uses to tell agents what this runtime
can and cannot do — never hand-edit the JSON, change this script or
requirements.txt instead.
"""

import hashlib
import json
import os
import platform
import subprocess
import sys
from importlib import metadata


def command_version(*command: str) -> str:
    out = subprocess.run(command, capture_output=True, text=True, check=True)
    return out.stdout.strip()


def optional_command_version(*command: str) -> str | None:
    """Report a tool the locked runtime may have removed on purpose.

    The immutable image strips npm/npx/corepack, so the manifest has to be able
    to say "absent" instead of failing the build. Only absence is tolerated: a
    tool that is present but broken still fails the build rather than being
    attested as missing.
    """
    try:
        return command_version(*command)
    except FileNotFoundError:
        return None


def installed_packages() -> dict[str, str]:
    return dict(
        sorted((dist.metadata["Name"], dist.version) for dist in metadata.distributions())
    )


def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    version = os.environ.get("RUNTIME_VERSION")
    if not version:
        raise SystemExit("RUNTIME_VERSION must be set at build time")
    supervisor_path = os.environ.get("EXEC_SUPERVISOR_PATH")
    if not supervisor_path or not os.path.isabs(supervisor_path):
        raise SystemExit("EXEC_SUPERVISOR_PATH must be an absolute path")
    command_uid = int(os.environ.get("SANDBOX_COMMAND_UID", "0"))
    command_gid = int(os.environ.get("SANDBOX_COMMAND_GID", "0"))
    if command_uid <= 0 or command_gid <= 0:
        raise SystemExit("SANDBOX_COMMAND_UID and SANDBOX_COMMAND_GID must be non-root")
    managed_environment = os.environ.get("MANAGED_ENVIRONMENT")
    if managed_environment not in {"mutable", "immutable"}:
        raise SystemExit("MANAGED_ENVIRONMENT must be mutable or immutable")

    manifest = {
        "schema_version": 2,
        "image_version": version,
        # The consumers key their capability decisions off this, and
        # features.managed_environment_mutation must agree with it:
        # agentarea_execution.models.RuntimeManifest.validate_profile_features
        # and runtimeinfo.Manifest.Validate both reject a disagreement.
        "managed_environment": managed_environment,
        "python": {
            "version": platform.python_version(),
            "executable": sys.executable,
        },
        "node": {
            "version": command_version("node", "--version"),
            "npm_version": optional_command_version("npm", "--version"),
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
        "execution_supervisor": {
            "path": supervisor_path,
            "sha256": file_sha256(supervisor_path),
            "protocol_version": 1,
            "command_uid": command_uid,
            "command_gid": command_gid,
        },
    }
    json.dump(manifest, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
