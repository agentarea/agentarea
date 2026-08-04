"""Sandbox runtime discovery and prompt rendering."""

import logging
from typing import Any

import httpx

from ..models import (
    CapabilityUnavailableResult,
    RuntimeDiscoveryResult,
    RuntimeManifest,
)

logger = logging.getLogger(__name__)


async def fetch_runtime_manifest(
    mcp_manager_url: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> RuntimeDiscoveryResult:
    url = f"{mcp_manager_url.rstrip('/')}/runtime/manifest"
    try:
        async with httpx.AsyncClient(timeout=10.0, transport=transport) as client:
            response = await client.get(url)
            response.raise_for_status()
        return RuntimeDiscoveryResult(manifest=RuntimeManifest.model_validate(response.json()))
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("runtime manifest fetch failed from %s", url, exc_info=True)
        return RuntimeDiscoveryResult(error=f"runtime manifest unavailable: {exc}")


def render_runtime_prompt(
    result: RuntimeDiscoveryResult,
    *,
    has_org_context: bool = False,
) -> str:
    manifest = result.manifest
    if manifest is None:
        return (
            "\n\n# Runtime environment\n\n"
            "Runtime capabilities could not be discovered. Do not assume a browser or "
            "an undeclared package is available."
        )

    package_names = ", ".join(sorted(manifest.packages, key=str.casefold))
    if manifest.features.browser == "none":
        browser_policy = (
            "Browser automation: unavailable in this runtime. If the task requires a browser, "
            "report blocked/capability_unavailable instead of claiming completion."
        )
    else:
        browser_policy = "Browser automation: Playwright is available."

    org_context_line = (
        "- Organization library: read the organization's shared files with the "
        "`list_org_files` and `read_org_file` tools (read-only). It is never changed by "
        "anything you do in the sandbox.\n"
        if has_org_context
        else ""
    )

    return (
        "\n\n# Runtime environment\n\n"
        f"- Image: {manifest.image_version}\n"
        f"- Python: {manifest.python.version}\n"
        f"- Node: {manifest.node.version} (npm {manifest.node.npm_version})\n"
        f"- Managed environment: {manifest.managed_environment}\n"
        f"- Preinstalled Python packages: {package_names or 'none declared'}\n"
        f"- {browser_policy}\n"
        "- Arbitrary workspace code is supported. Network access and managed-environment "
        "behavior are defined by the active runtime."
        "\n\n# Workspace and context\n\n"
        f"{org_context_line}"
        "- Your working directory is the live task workspace. User-provided inputs are under "
        "`/workspace/inputs`. File and shell tools operate on the same live filesystem.\n"
        "- Live workspace files are ephemeral. A file survives the task only if you list its "
        "workspace-relative path in completion `artifacts`; everything else is discarded with "
        "the sandbox. List only user-facing outputs, not caches, dependencies, or intermediate "
        "files. A file written outside `/workspace` is scratch and cannot be kept.\n"
        "- Binary deliverables (.xlsx, .pptx, .docx, .pdf, images): the file tool saves text "
        "only, so writing binary through it corrupts the file. Generate them by running a "
        "program in the shell that writes the file into your working directory, using a library "
        "from the preinstalled packages listed above, then list that path in `artifacts`."
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
) -> dict[str, Any]:
    if result.manifest is None:
        return {
            "runtime_discovery_error": result.error or "runtime manifest unavailable",
        }
    return {
        "runtime_version": result.manifest.image_version,
        "managed_environment": result.manifest.managed_environment,
    }
