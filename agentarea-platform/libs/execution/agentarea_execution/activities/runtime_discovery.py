"""Sandbox runtime discovery and prompt rendering."""

from typing import Any, Literal

import httpx

from ..models import (
    CapabilityUnavailableResult,
    RuntimeDiscoveryResult,
    RuntimeManifest,
)


async def fetch_runtime_manifest(
    mcp_manager_url: str,
    *,
    package_install: Literal["allowed", "locked"] = "allowed",
    transport: httpx.AsyncBaseTransport | None = None,
) -> RuntimeDiscoveryResult:
    url = f"{mcp_manager_url.rstrip('/')}/runtime/manifest"
    try:
        async with httpx.AsyncClient(timeout=10.0, transport=transport) as client:
            response = await client.get(
                url,
                params={"package_install": package_install},
            )
            response.raise_for_status()
        return RuntimeDiscoveryResult(manifest=RuntimeManifest.model_validate(response.json()))
    except (httpx.HTTPError, ValueError) as exc:
        return RuntimeDiscoveryResult(error=f"runtime manifest unavailable: {exc}")


def render_runtime_prompt(
    result: RuntimeDiscoveryResult,
    *,
    package_install: str = "allowed",
) -> str:
    manifest = result.manifest
    if manifest is None:
        return (
            "\n\n# Runtime environment\n\n"
            "Runtime capabilities could not be discovered. Do not assume a browser or "
            "an undeclared package is available."
        )

    package_names = ", ".join(sorted(manifest.packages, key=str.casefold))
    compatible = (
        package_install == "allowed" and manifest.managed_environment == "mutable"
    ) or (package_install == "locked" and manifest.managed_environment == "immutable")
    if package_install == "allowed":
        environment_policy = (
            "Package installation profile: allowed. The selected runtime must expose a mutable "
            "managed Python environment before pip commands can run."
        )
    else:
        environment_policy = (
            "Package installation profile: locked. The selected runtime must expose an "
            "immutable managed Python environment with pip removed."
        )
    compatibility_policy = (
        "The active runtime satisfies the requested package-install profile."
        if compatible
        else "The active runtime does not satisfy this profile; sandbox execution will fail closed."
    )

    if manifest.features.browser == "none":
        browser_policy = (
            "Browser automation: unavailable in this runtime. If the task requires a browser, "
            "report blocked/capability_unavailable instead of claiming completion."
        )
    else:
        browser_policy = "Browser automation: Playwright is available."

    return (
        "\n\n# Runtime environment\n\n"
        f"- Image: {manifest.image_version}\n"
        f"- Python: {manifest.python.version}\n"
        f"- Node: {manifest.node.version} (npm {manifest.node.npm_version})\n"
        f"- Managed environment: {manifest.managed_environment}\n"
        f"- Preinstalled Python packages: {package_names or 'none declared'}\n"
        f"- {browser_policy}\n"
        f"- {environment_policy}\n"
        f"- {compatibility_policy}\n"
        "- Arbitrary code can still be downloaded and run inside the writable task workspace; "
        "the managed-environment profile is not an egress or workspace-code restriction."
    )


def require_runtime_capability(
    result: RuntimeDiscoveryResult,
    capability: str,
) -> CapabilityUnavailableResult | None:
    manifest = result.manifest
    declared_capabilities = {"python", "node", "managed_environment"}
    available = manifest is not None and (
        capability in declared_capabilities
        or (capability == "browser" and manifest.features.browser != "none")
    )
    if available:
        return None
    return CapabilityUnavailableResult(
        capability=capability,
        runtime_version=manifest.image_version if manifest else None,
    )


def runtime_event_data(
    result: RuntimeDiscoveryResult,
    *,
    package_install: str = "allowed",
) -> dict[str, Any]:
    if result.manifest is None:
        return {
            "runtime_discovery_error": result.error or "runtime manifest unavailable",
            "package_install": package_install,
            "runtime_profile_compatible": False,
        }
    compatible = (
        package_install == "allowed"
        and result.manifest.managed_environment == "mutable"
    ) or (
        package_install == "locked"
        and result.manifest.managed_environment == "immutable"
    )
    return {
        "runtime_version": result.manifest.image_version,
        "managed_environment": result.manifest.managed_environment,
        "package_install": package_install,
        "runtime_profile_compatible": compatible,
    }
