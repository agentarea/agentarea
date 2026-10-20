"""Registry service — manages external registries and their catalog items.

Dispatches sync/create by registry_type:
  - "mcp_servers" → MCPServer specs
  - "skills" → Skill records
  - "llm_providers" → ProviderSpec
  - "llm_models" → ModelSpec (references provider by provider_key)
  - "agents" → catalog-only built-in agents (ADR-003): the registry_item IS
    the definition; no tenant `agents` row is materialized on sync.
  - "bundles" → catalog-only installable bundles: the registry_item.spec IS
    the canonical Bundle definition. Nothing is materialized on sync; the
    bundle is provisioned into a workspace on demand via BundleService.install.
  - "source_types" → catalog-only event source types (ADR-0040): the
    registry_item.spec IS the entry; streams read it by slug.

Source format auto-detected (JSON or YAML).
Entity-specific details (connection_type, source_type) live in spec JSONB.
"""

import asyncio
import json
import logging
import re
import urllib.error
import urllib.request
from collections.abc import Awaitable, Callable, Collection
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx
import yaml
from agentarea_common.constants import PLATFORM_WORKSPACE_ID, REGISTRY_TRUST_LEVELS
from agentarea_common.money import to_optional_money
from agentarea_common.outbound import Destination, outbound_client
from agentarea_common.utils.outbound_tls import outbound_ssl_context
from agentarea_common.utils.slug import generate_slug
from agentarea_common.utils.untrusted_yaml import load_untrusted_yaml
from agentarea_common.utils.url_safety import (
    OutboundPolicy,
    UnsafeUrlError,
    validate_outbound_url,
)
from agentarea_llm.domain.model_kind import ModelKind
from agentarea_mcp.domain.env_schema import derive_env_schema_from_spec, normalize_env_schema
from agentarea_mcp.infrastructure.repository import MCPServerRepository
from sqlalchemy.exc import SQLAlchemyError

from agentarea_registry.application.catalog_facets import apply_facets, derive_facets
from agentarea_registry.application.github_index import (
    GitHubIndexTooLargeError,
    GitHubSource,
    GitHubTreeTruncatedError,
    build_github_skill_index,
    is_github_repo,
)
from agentarea_registry.domain.models import (
    DEFAULT_REGISTRY_PRIORITY,
    REGISTRY_MODES,
    REGISTRY_SCOPES,
    WORKSPACE_REGISTRY_TYPES,
    Registry,
    RegistryItem,
)
from agentarea_registry.infrastructure.github_client import GitHubApiError, HttpGitHubSource
from agentarea_registry.infrastructure.repository import (
    DEFAULT_CATALOG_SORT,
    RegistryItemRepository,
    RegistryRepository,
)

logger = logging.getLogger(__name__)

# Per-socket-operation timeout for fetching a catalog over HTTP. urllib applies
# it to each connect and read rather than to the transfer as a whole, so this
# bounds a stalled host, not a large catalog. The previous 120s bound outlived
# both the readiness and the liveness probe, so a hung source took the pod down
# with it before the fetch ever gave up.
SOURCE_FETCH_TIMEOUT_SECONDS = 30
# Part of the stored ETag: bump it when parsing or facets change, so the next
# sync re-applies every source instead of skipping the unchanged ones.
SYNC_FORMAT = "3"
# A workspace's index is a member-supplied URL: read within these bounds, so a
# hostile or broken one costs one bounded request and no more.
MAX_SOURCE_BYTES = 5 * 1024 * 1024
# YAML is parsed in pure Python, seconds per megabyte: JSON keeps the full cap.
MAX_YAML_SOURCE_BYTES = 1024 * 1024
MAX_YAML_NODES = 200_000
SOURCE_DEADLINE_SECONDS = 60.0
MAX_SOURCE_ITEMS = 2000
MAX_SOURCE_REDIRECTS = 5
# Skill folders one workspace's GitHub repository may hold: a mirror sync reads
# each from GitHub, whose budget every tenant shares.
MAX_WORKSPACE_GITHUB_SKILLS = 200
# A whole sync of one workspace registry, so one cannot hold up the next.
WORKSPACE_SYNC_DEADLINE_SECONDS = 120.0

VALID_REGISTRY_TYPES = (
    "mcp_servers",
    "skills",
    "llm_providers",
    "llm_models",
    "agents",
    "bundles",
    "source_types",
)
VALID_SOURCE_TYPES = ("url", "github", "api", "managed")
# What a workspace admin may point a workspace registry at: an index in the
# platform format, or a GitHub repository whose folders are skills.
WORKSPACE_SOURCE_TYPES = ("url", "github")
# Trust a workspace may claim for its own registry; official and verified are
# the platform's to give.
WORKSPACE_TRUST_LEVELS = ("private", "community")

# Resolves a registry's credentials reference to the value, at sync time.
CredentialsResolver = Callable[[Registry], Awaitable[str]]
# Stores one mirror-mode item's content (its spec) as an immutable package and
# answers where, which the item's spec keeps as ``package`` (ADR-0044).
ItemContentMirror = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
# Opened once per sync of a registry, with the token its credentials resolve to.
ContentMirror = Callable[[Registry, str | None], ItemContentMirror]

# Top-level catalog key -> registry type. Each catalog document carries exactly
# one of these keys, so the registry type can be inferred from the payload shape
# when it is not stated explicitly.
TYPE_BY_TOPLEVEL_KEY = {
    "servers": "mcp_servers",
    "skills": "skills",
    "providers": "llm_providers",
    "models": "llm_models",
    "agents": "agents",
    "bundles": "bundles",
    "source_types": "source_types",
}


class RegistryNotFoundError(ValueError):
    """A requested catalog registry does not exist."""


class CatalogItemNotFoundError(ValueError):
    """A requested catalog item does not exist."""


class CatalogItemAlreadyExistsError(ValueError):
    """A registry already contains the requested external identifier."""


class RegistrySyncError(Exception):
    """A sync failed for a reason whose message is safe to show the registry's owner."""


class RegistrySourceError(RegistrySyncError):
    """The source could not be read, or what it holds is not an index."""


class RegistrySyncRefusedError(ValueError):
    """The request asks for a sync this registry does not have: the caller's error."""


class RegistryConfigurationError(RegistrySyncError, ValueError):
    """The registry asks for something this sync was not given."""


def sync_error_message(error: BaseException) -> str:
    """What a failed sync records and answers: a classification, never the error's text.

    The text of a fetch or parse error can quote what the source returned, or
    where it was fetched from, and a workspace's source is a URL a member chose.
    """
    if isinstance(error, (RegistrySyncError, GitHubTreeTruncatedError, GitHubIndexTooLargeError)):
        return str(error)
    if isinstance(error, GitHubApiError):
        if error.status_code is None:
            return "GitHub returned something this sync cannot read"
        return f"GitHub answered {error.status_code}"
    if isinstance(error, urllib.error.HTTPError):
        return f"the source answered HTTP {error.code}"
    if isinstance(error, (httpx.HTTPError, urllib.error.URLError, OSError)):
        return "the source could not be reached"
    if isinstance(error, (json.JSONDecodeError, yaml.YAMLError, UnicodeDecodeError)):
        return "the source is not a valid JSON or YAML index"
    if isinstance(error, UnsafeUrlError):
        return "the source could not be reached"
    if isinstance(error, ValueError):
        # Our own validation of an entry, naming what the index published.
        return str(error)
    return "the sync failed; the server log has the cause"


def _parse_untrusted(body: bytes) -> Any:
    """CPU-bound: run it in a worker thread, never on the event loop."""
    try:
        text = body.decode("utf-8")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            if len(body) > MAX_YAML_SOURCE_BYTES:
                raise RegistrySourceError(
                    f"the source is a YAML index over {_size(MAX_YAML_SOURCE_BYTES)}; "
                    "publish it as JSON"
                ) from None
            return load_untrusted_yaml(
                text, max_nodes=MAX_YAML_NODES, max_bytes=MAX_YAML_SOURCE_BYTES
            )
    except (UnicodeDecodeError, yaml.YAMLError) as e:
        raise RegistrySourceError("the source is not a valid JSON or YAML index") from e


def _size(n: int) -> str:
    mb = 1024 * 1024
    return f"{n // mb} MB" if n >= mb else f"{n // 1024} KB"


def _member_client(**kwargs: Any) -> httpx.AsyncClient:
    return outbound_client(Destination.MEMBER, **kwargs)


# Where a curator can declare an item's rank explicitly, instead of relying on
# its position in the published document. The namespaced spelling is what an
# AgentArea-curated entry uses inside an upstream MCP server's `metadata`,
# which is shared with the official registry schema.
RANK_KEYS = ("recommendation_rank", "agentarea:recommendation_rank")


def validated_registry_priority(value: Any) -> int:
    """A usable registry ordering weight, or a rejection.

    ``None`` is "unspecified" and takes the default. Anything else must be a
    non-negative int: a stray string or a negative number would silently
    reorder an entire source ahead of the curated catalog, which is worse than
    a reconcile that stops and says so.
    """
    if value is None:
        return DEFAULT_REGISTRY_PRIORITY
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"recommendation_priority must be a non-negative integer, got {value!r}")
    return value


_GITHUB_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_GIT_SHA = re.compile(r"[0-9a-f]{40}")
_GIT_REF = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._/-]{0,254}")


def _check_git_ref(ref: str | None) -> None:
    if ref is None:
        return
    if not _GIT_REF.fullmatch(ref) or ".." in ref or "//" in ref or ref.endswith(("/", ".lock")):
        raise ValueError("source_ref must be a branch, tag or commit name")


def _check_source_path(path: str | None) -> None:
    if path is None:
        return
    stripped = path.strip("/")
    if stripped and (
        {"", ".", ".."} & set(stripped.split("/")) or "\\" in stripped or "\x00" in stripped
    ):
        raise ValueError("source_path must be a plain relative folder path")


def _require_public_https(url: str) -> None:
    refusal = "a workspace registry's index is a public https URL"
    if urlsplit(url).scheme != "https":
        raise ValueError(refusal)
    try:
        validate_outbound_url(url, policy=OutboundPolicy.from_env())
    except UnsafeUrlError as e:
        raise ValueError(refusal) from e


def validate_registry_source(
    *,
    registry_type: str,
    source_type: str,
    source_url: str,
    scope: str,
    workspace_id: str | None,
    mode: str,
    trust: str,
    credentials: bool = False,
    source_ref: str | None = None,
    source_path: str | None = None,
) -> None:
    """Refuse a registry the platform could not sync or must not let a workspace add."""
    if scope not in REGISTRY_SCOPES:
        raise ValueError(f"scope must be one of {REGISTRY_SCOPES}")
    if mode not in REGISTRY_MODES:
        raise ValueError(f"mode must be one of {REGISTRY_MODES}")
    if trust not in REGISTRY_TRUST_LEVELS:
        raise ValueError(f"trust must be one of {REGISTRY_TRUST_LEVELS}")
    _check_git_ref(source_ref)
    _check_source_path(source_path)
    if source_type == "github":
        if registry_type != "skills":
            raise ValueError("a GitHub repository source holds skills")
        if not is_github_repo(source_url):
            raise ValueError("a GitHub source_url is the repository as owner/repo")
    if credentials and registry_type == "skills" and mode != "mirror":
        # Credentials are resolved for a sync only; an install of an upstream
        # item fetches its content with none.
        raise ValueError("a skills registry read with credentials mirrors its content")
    if scope == "platform":
        if workspace_id is not None:
            raise ValueError("a platform registry belongs to no workspace")
        return
    if not workspace_id:
        raise ValueError("a workspace registry needs its workspace")
    if registry_type not in WORKSPACE_REGISTRY_TYPES:
        raise ValueError(f"a workspace registry holds {' or '.join(WORKSPACE_REGISTRY_TYPES)}")
    if source_type not in WORKSPACE_SOURCE_TYPES:
        raise ValueError(f"a workspace registry's source_type is one of {WORKSPACE_SOURCE_TYPES}")
    if trust not in WORKSPACE_TRUST_LEVELS:
        raise ValueError(f"a workspace registry's trust is one of {WORKSPACE_TRUST_LEVELS}")
    if source_type == "url":
        _require_public_https(source_url)


def rank_fields(*mappings: Any) -> dict[str, int]:
    """``{"recommendation_rank": n}`` when a curator declared one, else ``{}``.

    Empty is meaningful: the parser's fallback is the entry's position in the
    source document, so a missing or malformed rank keeps publication order
    rather than collapsing a whole source onto one rank.
    """
    for mapping in mappings:
        if not isinstance(mapping, dict):
            continue
        for key in RANK_KEYS:
            value = mapping.get(key)
            # `isinstance(True, int)` is True, and a negative rank would outrank
            # every curated entry.
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                continue
            return {"recommendation_rank": value}
    return {}


def _registry_argument_tokens(arguments: Any) -> tuple[list[str], list[str]] | None:
    """Extract concrete MCP registry arguments without inventing required inputs."""
    if not isinstance(arguments, list):
        return None if arguments is not None else ([], [])

    tokens: list[str] = []
    positional: list[str] = []
    for argument in arguments:
        if not isinstance(argument, dict):
            return None
        value = argument.get("value")
        if value is None:
            value = argument.get("default")
        required = argument.get("isRequired")
        if required is None:
            required = argument.get("required", False)
        if value is None:
            if required:
                return None
            continue
        is_boolean = isinstance(value, bool)
        if is_boolean:
            value = str(value).lower()
        elif isinstance(value, (str, int, float)):
            value = str(value)
        else:
            return None
        if not value:
            if required:
                return None
            continue

        argument_type = argument.get("type", "positional")
        if argument_type == "positional":
            tokens.append(value)
            if not value.startswith("-"):
                positional.append(value)
        elif argument_type == "named":
            name = argument.get("name")
            if not isinstance(name, str) or not name:
                return None
            if is_boolean:
                if value == "true":
                    tokens.append(name)
            else:
                tokens.append(f"{name}={value}")
        else:
            return None
    return tokens, positional


def _command_package_args(
    package: dict[str, Any], registry_type: str, server_version: str
) -> tuple[str, list[str]] | None:
    """Build a pinned command, or ``None`` when the package cannot run unattended.

    The registry rarely names an executable; then the package's default bin
    runs, which is how ``npx``/``uvx`` resolve a bare package. Only a required
    argument with no value, an unpinned version or an ambiguous entrypoint hides it.
    """
    package_name = package.get("name") or package.get("identifier")
    version = package.get("version") or server_version
    defaults = {"pypi": "uvx", "npm": "npx", "mcpb": "npx", "nuget": "dotnet"}
    runtime = package.get("runtimeHint") or defaults.get(registry_type)
    if (
        not isinstance(package_name, str)
        or not package_name
        or not isinstance(version, str)
        or not version
        or version.lower() == "latest"
        or runtime not in {"uvx", "npx", "bunx"}
    ):
        return None

    runtime_args = _registry_argument_tokens(package.get("runtimeArguments", []))
    package_args = _registry_argument_tokens(package.get("packageArguments", []))
    if runtime_args is None or package_args is None:
        return None
    runtime_tokens, entrypoints = runtime_args
    if len(entrypoints) > 1:
        return None
    entrypoint = entrypoints[0] if entrypoints else None
    if entrypoint is not None:
        if "/" in entrypoint or "\\" in entrypoint or entrypoint in {".", ".."}:
            return None
        runtime_tokens = [token for token in runtime_tokens if token != entrypoint]
    if any(token in {"--from", "--package"} for token in runtime_tokens):
        return None

    package_tokens, _ = package_args
    if runtime == "uvx":
        if registry_type != "pypi":
            return None
        if entrypoint is None:
            return runtime, [*runtime_tokens, f"{package_name}@{version}", *package_tokens]
        return runtime, [
            *runtime_tokens,
            "--from",
            f"{package_name}=={version}",
            entrypoint,
            *package_tokens,
        ]
    if registry_type not in {"npm", "mcpb"}:
        return None
    if entrypoint is None:
        if registry_type != "npm":
            # An mcpb package is a bundle file, not an npm package with a bin.
            return None
        assume_yes = [] if {"-y", "--yes"} & set(runtime_tokens) else ["-y"]
        return runtime, [
            *assume_yes,
            *runtime_tokens,
            f"{package_name}@{version}",
            *package_tokens,
        ]
    return runtime, [
        *runtime_tokens,
        "--package",
        f"{package_name}@{version}",
        entrypoint,
        *package_tokens,
    ]


class RegistryService:
    """Manages registry CRUD, sync, and spec update operations."""

    def __init__(
        self,
        registry_repo: RegistryRepository,
        item_repo: RegistryItemRepository,
        server_repo: MCPServerRepository,
        skill_repo: Any | None = None,
        provider_spec_repo: Any | None = None,
        model_spec_repo: Any | None = None,
        agent_repo: Any | None = None,
        credentials_resolver: CredentialsResolver | None = None,
        github_source_factory: Callable[[str | None], GitHubSource] = HttpGitHubSource,
        content_mirror: ContentMirror | None = None,
        untrusted_client: Callable[..., httpx.AsyncClient] = _member_client,
    ):
        self.untrusted_client = untrusted_client
        self.credentials_resolver = credentials_resolver
        self.content_mirror = content_mirror
        self.github_source_factory = github_source_factory
        self.registry_repo = registry_repo
        self.item_repo = item_repo
        self.server_repo = server_repo
        self.skill_repo = skill_repo
        self.provider_spec_repo = provider_spec_repo
        self.model_spec_repo = model_spec_repo
        self.agent_repo = agent_repo

    # ── Registry CRUD ──

    async def create_registry(
        self,
        name: str,
        registry_type: str,
        source_type: str,
        source_url: str | None,
        description: str | None = None,
        sync_mode: str = "manual",
        recommendation_priority: int | None = None,
        *,
        scope: str = "platform",
        workspace_id: str | None = None,
        mode: str = "mirror",
        trust: str = "official",
        credentials_secret_ref: UUID | None = None,
        source_ref: str | None = None,
        source_path: str | None = None,
    ) -> Registry:
        if registry_type not in VALID_REGISTRY_TYPES:
            raise ValueError(f"registry_type must be one of {VALID_REGISTRY_TYPES}")
        if source_type not in VALID_SOURCE_TYPES:
            raise ValueError(f"source_type must be one of {VALID_SOURCE_TYPES}")
        if source_type == "managed":
            source_url = source_url or "managed://catalog"
        elif not source_url:
            raise ValueError("source_url is required for synchronized registries")
        # In a thread: a workspace index's host is resolved, and a slow name
        # server would hold up the event loop.
        await asyncio.to_thread(
            validate_registry_source,
            registry_type=registry_type,
            source_type=source_type,
            source_url=source_url,
            scope=scope,
            workspace_id=workspace_id,
            mode=mode,
            trust=trust,
            credentials=credentials_secret_ref is not None,
            source_ref=source_ref,
            source_path=source_path,
        )
        return await self.registry_repo.create(
            name=name,
            registry_type=registry_type,
            source_type=source_type,
            source_url=source_url,
            description=description,
            sync_mode=sync_mode,
            recommendation_priority=validated_registry_priority(recommendation_priority),
            scope=scope,
            workspace_id=workspace_id,
            mode=mode,
            trust=trust,
            credentials_secret_ref=credentials_secret_ref,
            source_ref=source_ref,
            source_path=source_path,
        )

    async def get_registry(self, registry_id: UUID) -> Registry | None:
        return await self.registry_repo.get_by_id(registry_id)

    async def list_registries(
        self, active_only: bool = False, registry_type: str | None = None
    ) -> list[Registry]:
        if active_only:
            return await self.registry_repo.list_active(registry_type=registry_type)
        if registry_type:
            return await self.registry_repo.list_all(registry_type=registry_type)
        return await self.registry_repo.list_all()

    async def update_registry(self, registry_id: UUID, **fields) -> Registry | None:
        if fields.get("source_type", VALID_SOURCE_TYPES[0]) not in VALID_SOURCE_TYPES:
            raise ValueError(f"source_type must be one of {VALID_SOURCE_TYPES}")
        if {
            "source_type",
            "source_url",
            "source_ref",
            "source_path",
            "mode",
            "trust",
            "credentials_secret_ref",
        } & fields.keys():
            current = await self.registry_repo.get_by_id(registry_id)
            if current is None:
                return None
            await asyncio.to_thread(
                validate_registry_source,
                registry_type=current.registry_type,
                source_type=fields.get("source_type", current.source_type),
                source_url=fields.get("source_url", current.source_url),
                scope=current.scope,
                workspace_id=current.workspace_id,
                mode=fields.get("mode", current.mode),
                trust=fields.get("trust", current.trust),
                credentials=fields.get("credentials_secret_ref", current.credentials_secret_ref)
                is not None,
                source_ref=fields.get("source_ref", current.source_ref),
                source_path=fields.get("source_path", current.source_path),
            )
        if {"source_type", "source_url", "source_ref", "source_path", "mode"} & fields.keys():
            # Another source, or one now mirrored: what the last sync applied
            # says nothing about it.
            fields["source_etag"] = None
        if "recommendation_priority" in fields:
            fields["recommendation_priority"] = validated_registry_priority(
                fields["recommendation_priority"]
            )
        return await self.registry_repo.update(registry_id, **fields)

    async def delete_registry(self, registry_id: UUID) -> bool:
        return await self.registry_repo.delete(registry_id)

    # ── What the caller's workspace may see (ADR-0044) ──

    async def list_visible_registries(
        self,
        active_only: bool = False,
        registry_type: str | None = None,
        scope: str | None = None,
    ) -> list[Registry]:
        return await self.registry_repo.list_visible(
            active_only=active_only, registry_type=registry_type, scope=scope
        )

    async def get_visible_registry(self, registry_id: UUID) -> Registry | None:
        return await self.registry_repo.get_visible(registry_id)

    async def get_workspace_registry(self, registry_id: UUID, workspace_id: str) -> Registry | None:
        """One of ``workspace_id``'s own registries; the platform's are not its to change."""
        registry = await self.registry_repo.get_by_id(registry_id)
        if registry is None or registry.scope != "workspace":
            return None
        return registry if registry.workspace_id == workspace_id else None

    async def get_platform_registry(self, registry_id: UUID) -> Registry | None:
        registry = await self.registry_repo.get_by_id(registry_id)
        return registry if registry is not None and registry.scope == "platform" else None

    async def registries_by_id(self, ids: set[str]) -> dict[str, Registry]:
        """The registries of a page of items, for the source and trust on each card."""
        return {str(r.id): r for r in await self.registry_repo.get_many(ids)}

    # ── Catalog browsing ──

    async def list_items(
        self, registry_id: UUID, limit: int = 50, offset: int = 0
    ) -> list[RegistryItem]:
        if await self.registry_repo.get_visible(registry_id) is None:
            raise RegistryNotFoundError(f"Registry {registry_id} not found")
        return await self.item_repo.list_by_registry(registry_id, limit=limit, offset=offset)

    async def browse_catalog(
        self,
        registry_type: str,
        query: str | None = None,
        category: str | None = None,
        protocol: str | None = None,
        hosting: str | None = None,
        pricing: str | None = None,
        sort: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[
        list[RegistryItem],
        int,
        list[tuple[str, int]],
        list[tuple[str, int]],
        list[tuple[str, int]],
        list[tuple[str, int]],
    ]:
        """One page of a type's catalog, its total, and its facets.

        Backs the /explore gallery. All of them come from the same filter so the
        page, the "is there more" signal and the sidebar counts can never
        disagree with each other.
        """
        items, total = await self.item_repo.browse(
            registry_type=registry_type,
            q=query,
            category=category,
            protocol=protocol,
            hosting=hosting,
            pricing=pricing,
            sort=sort or DEFAULT_CATALOG_SORT,
            limit=limit,
            offset=offset,
        )
        categories = await self.item_repo.category_counts(
            registry_type, q=query, protocol=protocol, hosting=hosting, pricing=pricing
        )
        protocols = await self.item_repo.protocol_counts(
            registry_type, q=query, category=category, hosting=hosting, pricing=pricing
        )
        hostings = await self.item_repo.hosting_counts(
            registry_type, q=query, category=category, protocol=protocol, pricing=pricing
        )
        pricings = await self.item_repo.pricing_counts(
            registry_type, q=query, category=category, protocol=protocol, hosting=hosting
        )
        return items, total, categories, protocols, hostings, pricings

    async def search_catalog(
        self,
        query: str | None = None,
        tag: str | None = None,
        update_available: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[RegistryItem]:
        return await self.item_repo.search(
            query_str=query,
            tag=tag,
            update_available=update_available,
            limit=limit,
            offset=offset,
        )

    async def count_items(self, registry_id: UUID) -> int:
        return await self.item_repo.count_by_registry(registry_id)

    async def get_item(self, item_id: UUID) -> RegistryItem | None:
        """The item, unless it belongs to another workspace's registry."""
        return await self.item_repo.get_visible(item_id)

    async def create_catalog_item(
        self,
        registry_id: UUID,
        *,
        external_id: str,
        name: str,
        description: str | None = None,
        version: str | None = None,
        spec: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        recommendation_rank: int | None = None,
    ) -> RegistryItem:
        """Create one platform-managed catalog definition.

        Directly managed items stay as catalog projections. Workspace entities
        are materialized only when a user installs or connects them; publishing
        a connector must not create a tenant-shaped global entity.
        """
        registry = await self.registry_repo.get_by_id(registry_id)
        if not registry:
            raise RegistryNotFoundError(f"Registry {registry_id} not found")
        if registry.source_type != "managed":
            raise ValueError("Catalog items can only be written to a managed registry")

        existing = await self.item_repo.get_by_external_id(registry_id, external_id)
        if existing:
            raise CatalogItemAlreadyExistsError(
                f"Catalog item {external_id!r} already exists in registry {registry_id}"
            )

        item_spec = spec or {}
        item_tags = tags or []
        facets = derive_facets(registry.registry_type, name, item_spec, item_tags)
        item = await self.item_repo.create(
            registry_id=registry_id,
            external_id=external_id,
            name=name,
            description=description,
            version=version,
            spec=item_spec,
            tags=item_tags,
            **facets._asdict(),
            # A managed registry has no source order to take a position from,
            # so an unranked publication goes to the end rather than tying with
            # the existing catalog and jumping it on the alphabetical tiebreak.
            recommendation_rank=(
                await self.item_repo.next_recommendation_rank(registry_id)
                if recommendation_rank is None
                else recommendation_rank
            ),
        )
        await self.registry_repo.update(
            registry_id,
            item_count=await self.item_repo.count_by_registry(registry_id),
        )
        return item

    async def update_catalog_item(
        self,
        item_id: UUID,
        **fields: Any,
    ) -> RegistryItem:
        """Update one item in a managed registry and recompute browse facets."""
        item = await self.item_repo.get_by_id(item_id)
        if not item:
            raise CatalogItemNotFoundError(f"Catalog item {item_id} not found")
        registry = await self.registry_repo.get_by_id(item.registry_id)
        if not registry:
            raise RegistryNotFoundError(f"Registry {item.registry_id} not found")
        if registry.source_type != "managed":
            raise ValueError("Catalog items can only be written in a managed registry")

        external_id = fields.get("external_id", item.external_id)
        if external_id != item.external_id:
            existing = await self.item_repo.get_by_external_id(item.registry_id, external_id)
            if existing:
                raise CatalogItemAlreadyExistsError(
                    f"Catalog item {external_id!r} already exists in registry {item.registry_id}"
                )

        name = fields.get("name", item.name)
        spec = fields.get("spec", item.spec)
        tags = fields.get("tags", item.tags)
        facets = derive_facets(registry.registry_type, name, spec, tags)
        fields.update(facets._asdict())
        updated = await self.item_repo.update(item_id, **fields)
        if updated is None:  # Defensive against a concurrent delete.
            raise CatalogItemNotFoundError(f"Catalog item {item_id} not found")
        return updated

    async def delete_catalog_item(self, item_id: UUID) -> None:
        """Remove one item from a managed registry."""
        item = await self.item_repo.get_by_id(item_id)
        if not item:
            raise CatalogItemNotFoundError(f"Catalog item {item_id} not found")
        registry = await self.registry_repo.get_by_id(item.registry_id)
        if not registry:
            raise RegistryNotFoundError(f"Registry {item.registry_id} not found")
        if registry.source_type != "managed":
            raise ValueError("Catalog items can only be written in a managed registry")

        if not await self.item_repo.delete(item_id):
            raise CatalogItemNotFoundError(f"Catalog item {item_id} not found")
        await self.registry_repo.update(
            registry.id,
            item_count=await self.item_repo.count_by_registry(registry.id),
        )

    # ── Sync ──

    # Cap on how many skip reasons ride along in the returned stats dict. A
    # catalog can fail validation on hundreds of items (e.g. a whole class of
    # priceless reserved-capacity SKUs); the full count is still reported via
    # `skipped`, this just bounds the payload. The WARNING log carries every
    # skip regardless of the cap.
    MAX_SKIPPED_DETAILS = 50

    async def sync_registry(self, registry_id: UUID, force: bool = False) -> dict[str, Any]:
        """Sync: fetch source, upsert catalog, auto-create entities for new items.

        A single item failing validation (e.g. an LLM model published with no
        price) must not cost the rest of the batch: such items are skipped and
        reported back in `skipped`/`skipped_items`, not silently dropped and
        not allowed to abort the sync.

        A source whose ETag is the one the last sync applied is not read again;
        ``force`` reads it anyway (after a change to how items are parsed).
        """
        registry = await self.registry_repo.get_by_id(registry_id)
        if not registry:
            raise RegistryNotFoundError(f"Registry {registry_id} not found")
        if registry.source_type == "managed":
            raise RegistrySyncRefusedError(
                "Managed registry items are changed through the catalog item API"
            )

        deadline = WORKSPACE_SYNC_DEADLINE_SECONDS if registry.scope == "workspace" else None
        try:
            try:
                async with asyncio.timeout(deadline):
                    return await self._sync(registry, force)
            except TimeoutError as e:
                raise RegistrySyncError(f"the sync took longer than {deadline:g} s") from e
        except Exception as e:
            logger.exception("Registry sync failed for %s", registry_id)
            try:
                await self.item_repo.session.rollback()
                await self.registry_repo.update(registry_id, last_sync_error=sync_error_message(e))
            except Exception:
                logger.exception("Could not record why registry %s failed to sync", registry_id)
            raise

    async def _sync(self, registry: Registry, force: bool) -> dict[str, Any]:
        registry_id = registry.id
        mirrors = registry.registry_type == "skills" and registry.mode == "mirror"
        if mirrors and self.content_mirror is None:
            raise RegistryConfigurationError(
                f"Registry {registry.id} mirrors its content but this sync has no store for it"
            )
        token = (
            await self._credentials(registry)
            if registry.source_type == "github" or mirrors
            else None
        )
        github: GitHubSource | None = None
        head = root_tree = ""
        if registry.source_type == "github":
            # A repository's version is its head commit, kept where an
            # index URL keeps its ETag.
            github = self.github_source_factory(token)
            head, root_tree = await github.head(registry.source_url, registry.source_ref)
            source_etag = head
        elif registry.scope == "workspace":
            source_etag = await self._untrusted_etag(registry.source_url)
        else:
            source_etag = await asyncio.to_thread(self._source_etag, registry.source_url)
        etag = f"{SYNC_FORMAT}:{source_etag}" if source_etag else None
        if not force and etag is not None and etag == registry.source_etag:
            await self.registry_repo.update(
                registry_id, last_synced_at=datetime.utcnow(), last_sync_error=None
            )
            return {
                "new_specs": 0,
                "updates_flagged": 0,
                "unchanged": registry.item_count,
                "total": registry.item_count,
                "skipped": 0,
                "skipped_items": [],
                "out_of_source": None,
                "deleted": 0,
                "source_unchanged": True,
            }

        if github is not None:
            parsed_items = await build_github_skill_index(
                github,
                repo=registry.source_url,
                commit=head,
                root_tree=root_tree,
                path=registry.source_path,
                max_skills=MAX_WORKSPACE_GITHUB_SKILLS if registry.scope == "workspace" else None,
            )
            for position, entry in enumerate(parsed_items):
                entry.setdefault("recommendation_rank", position)
        else:
            if registry.scope == "workspace":
                raw_data = await self._fetch_untrusted(registry.source_url)
            else:
                # In a worker thread, not on the loop: _fetch_source is a
                # blocking urlopen, and the API serves every request from one
                # event loop, so calling it here directly froze the whole
                # process -- /health with it, which is what the probes poll.
                raw_data = await asyncio.to_thread(self._fetch_source, registry.source_url)
            try:
                # Off the loop: a whole catalog parses for as long as it is big.
                parsed_items = await asyncio.to_thread(
                    self._parse_source, registry.registry_type, raw_data
                )
            except ValueError as e:
                raise RegistrySourceError(f"the source is not a valid index: {e}") from e
            except (TypeError, AttributeError, KeyError) as e:
                raise RegistrySourceError("the source is not a valid index") from e
        if registry.scope == "workspace" and len(parsed_items) > MAX_SOURCE_ITEMS:
            raise RegistrySourceError(f"the source lists more than {MAX_SOURCE_ITEMS} items")
        parsed_items = self._dedupe(parsed_items)
        mirror = (
            self.content_mirror(registry, token)
            if mirrors and self.content_mirror is not None
            else None
        )

        new_specs = 0
        updates_flagged = 0
        unchanged = 0
        skipped = 0
        skipped_items: list[dict[str, str]] = []
        # One read for the whole registry: a lookup per item was a query per
        # catalog row on every sync, millions of them a day.
        existing_by_id = await self._items_by_external_id(registry_id)

        for item_data in parsed_items:
            external_id = item_data["external_id"]
            try:
                existing = existing_by_id.get(external_id)
                if mirror is not None:
                    item_data["spec"] = await self._mirrored_spec(
                        mirror, item_data.get("spec", {}), existing
                    )

                if existing:
                    previous_spec = dict(existing.spec or {})
                    for field in (
                        "name",
                        "description",
                        "spec",
                        "tags",
                        # Re-published in a different position means the
                        # curator moved it; keeping the old rank would pin
                        # the catalog to the order of the first ever sync.
                        "recommendation_rank",
                    ):
                        if field in item_data:
                            setattr(existing, field, item_data[field])
                    # Browse facets are derived from the fields just overwritten,
                    # so they have to be recomputed or the catalog keeps sorting
                    # and faceting this item by what it used to be.
                    apply_facets(existing, registry.registry_type)

                    new_version = item_data.get("version") or "latest"
                    existing.version = new_version

                    if existing.installed_version and existing.installed_version != new_version:
                        existing.update_available = True
                        updates_flagged += 1
                    else:
                        unchanged += 1

                    if registry.registry_type == "skills":
                        await self._drop_platform_skill(existing)

                    await self.item_repo.session.commit()
                    if registry.registry_type == "llm_models":
                        await self._resync_model_cache_prices(previous_spec, existing.spec)

                    # Backfill json_spec on linked entity if missing
                    if existing.installed_entity_id:
                        raw_spec = (existing.spec or {}).get("raw_spec")
                        if raw_spec:
                            await self._backfill_entity(
                                registry.registry_type,
                                existing,
                                registry_url=registry.source_url,
                            )
                else:
                    facets = derive_facets(
                        registry.registry_type,
                        item_data["name"],
                        item_data.get("spec", {}),
                        item_data.get("tags", []),
                    )
                    item = await self.item_repo.create(
                        registry_id=registry_id,
                        external_id=external_id,
                        name=item_data["name"],
                        description=item_data.get("description"),
                        version=item_data.get("version"),
                        spec=item_data.get("spec", {}),
                        tags=item_data.get("tags", []),
                        recommendation_rank=item_data.get("recommendation_rank", 0),
                        **facets._asdict(),
                    )
                    try:
                        entity_id = await self._create_entity(
                            registry.registry_type, item, registry_url=registry.source_url
                        )
                    except Exception:
                        # Don't leave a catalog row with no backing entity
                        # behind -- a rejected item must not appear browsable.
                        await self.item_repo.delete(item.id)
                        raise
                    await self.item_repo.update(
                        item.id,
                        installed_entity_id=entity_id,
                        installed_version=item.version or "latest",
                    )
                    existing_by_id[external_id] = item
                    new_specs += 1
            except Exception as e:
                logger.warning(
                    "Skipping catalog item %r in registry %s: %s",
                    external_id,
                    registry_id,
                    e,
                    exc_info=True,
                )
                if isinstance(e, SQLAlchemyError):
                    # A failed statement leaves the transaction unusable for
                    # every later item; rolling back expires what was loaded.
                    await self.item_repo.session.rollback()
                    existing_by_id = await self._items_by_external_id(registry_id)
                skipped += 1
                if len(skipped_items) < self.MAX_SKIPPED_DETAILS:
                    skipped_items.append(
                        {"external_id": external_id, "reason": sync_error_message(e)}
                    )

        # What the source no longer publishes leaves the catalog. An empty
        # parse is far likelier a broken source than an emptied one, so it
        # retires nothing.
        out_of_source = None
        deleted = 0
        if parsed_items:
            published = {item["external_id"] for item in parsed_items}
            out_of_source = await self.item_repo.mark_in_source(registry_id, published)
            if out_of_source:
                if registry.registry_type == "skills":
                    for item in existing_by_id.values():
                        if item.external_id not in published:
                            await self._drop_platform_skill(item)
                    await self.item_repo.session.commit()
                deleted = await self.item_repo.delete_unreferenced_out_of_source(registry_id)
                out_of_source -= deleted

        total = new_specs + updates_flagged + unchanged
        await self.registry_repo.update(
            registry_id,
            last_synced_at=datetime.utcnow(),
            last_sync_error=None,
            item_count=total,
            # A skipped item (a model whose provider has not synced yet) must
            # be retried by the next run, so the source counts as unread.
            source_etag=etag if skipped == 0 else None,
        )

        return {
            "new_specs": new_specs,
            "updates_flagged": updates_flagged,
            "unchanged": unchanged,
            "total": len(parsed_items),
            "skipped": skipped,
            "skipped_items": skipped_items,
            "out_of_source": out_of_source,
            "deleted": deleted,
        }

    async def retire_registry(self, registry_id: UUID, replacements: Collection[UUID] = ()) -> int:
        """Retire a registry no source feeds any more: everything in it is out of
        source, and what nothing uses is deleted. Returns how many items were.

        Uses of an item a ``replacements`` registry also publishes (the same
        ``external_id``) move to that item first, in the transaction that deletes
        what is then unused, so an install survives its registry being folded
        into another.
        """
        registry = await self.registry_repo.get_by_id(registry_id)
        if not registry:
            raise RegistryNotFoundError(f"Registry {registry_id} not found")
        if registry.is_active:
            await self.update_registry(registry_id, is_active=False)
        await self.item_repo.mark_in_source(registry_id, set())
        if registry.registry_type == "skills":
            for item in (await self._items_by_external_id(registry_id)).values():
                await self._drop_platform_skill(item)
            await self.item_repo.session.commit()
        moved = await self.item_repo.move_references(registry_id, replacements)
        if moved:
            logger.info("Moved %d uses of retired registry %s's items", moved, registry_id)
        return await self.item_repo.delete_unreferenced_out_of_source(registry_id)

    async def _items_by_external_id(self, registry_id: UUID) -> dict[str, RegistryItem]:
        # One read for the whole registry: a lookup per item was a query per
        # catalog row on every sync, millions of them a day.
        return {
            item.external_id: item for item in await self.item_repo.list_by_registry(registry_id)
        }

    @staticmethod
    def _dedupe(parsed_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """One entry per external_id: the last one published, at its first position."""
        by_id: dict[str, dict[str, Any]] = {}
        for item in parsed_items:
            by_id[item["external_id"]] = item
        if len(by_id) < len(parsed_items):
            logger.warning(
                "Source published %d duplicate catalog entries; kept the last of each",
                len(parsed_items) - len(by_id),
            )
        return list(by_id.values())

    @staticmethod
    async def _mirrored_spec(
        mirror: ItemContentMirror, spec: dict[str, Any], existing: RegistryItem | None
    ) -> dict[str, Any]:
        """``spec`` with the package its content is stored as.

        An entry the last sync already stored keeps that package: the content
        is the same, so storing it again would only spend reads (and, for a
        GitHub folder, the API budget).
        """
        if existing is not None:
            kept = dict(existing.spec or {})
            package = kept.pop("package", None)
            if package and kept == spec:
                return {**spec, "package": package}
        return {**spec, "package": await mirror(spec)}

    async def _credentials(self, registry: Registry) -> str | None:
        """The token a sync reads the source with; resolved now, never stored."""
        if registry.credentials_secret_ref is None:
            return None
        if self.credentials_resolver is None:
            raise RegistryConfigurationError(
                f"Registry {registry.id} has credentials but this sync has no way to resolve them"
            )
        return await self.credentials_resolver(registry)

    # ── Update specs ──

    async def update_item_spec(self, item_id: UUID) -> Any:
        """Apply the registry version to the installed entity."""
        item = await self.item_repo.get_by_id(item_id)
        if not item:
            raise ValueError(f"Registry item {item_id} not found")
        if not item.installed_entity_id:
            raise ValueError(f"Item {item.name} has no installed entity")
        if not item.update_available:
            raise ValueError(f"Item {item.name} is already up to date")

        registry = await self.registry_repo.get_by_id(item.registry_id)
        if not registry:
            raise ValueError(f"Registry {item.registry_id} not found")

        entity = await self._update_entity(
            registry.registry_type, item, registry_url=registry.source_url
        )
        await self.item_repo.update(
            item_id,
            update_available=False,
            installed_version=item.version or "latest",
        )
        return entity

    async def update_all_specs(self, registry_id: UUID) -> dict[str, int]:
        """Bulk-update all items with update_available=True."""
        items = await self.item_repo.list_by_registry(registry_id)
        updated = 0
        errors = 0
        for item in items:
            if not item.update_available:
                continue
            try:
                await self.update_item_spec(item.id)
                updated += 1
            except Exception as e:
                logger.warning(f"Failed to update {item.name}: {e}", exc_info=True)
                errors += 1
        return {"updated": updated, "errors": errors}

    # ── Entity dispatchers ──

    async def _create_entity(
        self, registry_type: str, item: RegistryItem, registry_url: str | None = None
    ) -> str | None:
        if registry_type == "mcp_servers":
            # API connectors share the user-facing Connections catalog but are
            # workspace materializations, not global MCPServer specifications.
            if (item.spec or {}).get("connection_type") == "openapi":
                return None
            return await self._create_mcp_server(item, registry_url=registry_url)
        elif registry_type == "skills":
            # Catalog-only, like agents (ADR-003): skills are read through the
            # catalog projection and forked into a workspace on use. Creating a
            # platform Skill row per catalog item left 220k unused rows on RU,
            # each with four ownership tuples in the authorization graph.
            return None
        elif registry_type == "llm_providers":
            return await self._create_llm_provider(item)
        elif registry_type == "llm_models":
            return await self._create_llm_model(item)
        elif registry_type == "agents":
            # Catalog-only (ADR-003): the registry_item is the built-in agent
            # definition; no tenant `agents` row is materialized on sync. A real
            # row is created copy-on-write when a user edits the catalog agent.
            return None
        elif registry_type == "bundles":
            # Catalog-only: the registry_item.spec is the canonical Bundle. It is
            # provisioned into a workspace on demand via BundleService.install, so
            # nothing is materialized on sync.
            return None
        elif registry_type == "source_types":
            # Catalog-only: streams read the entry from registry_items by slug.
            return None
        raise ValueError(f"Unknown registry_type: {registry_type}")

    async def _update_entity(
        self, registry_type: str, item: RegistryItem, registry_url: str | None = None
    ) -> Any:
        if registry_type == "mcp_servers":
            if (item.spec or {}).get("connection_type") == "openapi":
                return None
            return await self._update_mcp_server(item, registry_url=registry_url)
        elif registry_type == "skills":
            return None
        elif registry_type == "llm_providers":
            return await self._update_llm_provider(item)
        elif registry_type == "llm_models":
            return await self._update_llm_model(item)
        elif registry_type == "agents":
            # No materialized entity to update for catalog agents (ADR-003).
            return None
        elif registry_type in ("bundles", "source_types"):
            # No materialized entity to update for catalog bundles or source types.
            return None
        raise ValueError(f"Unknown registry_type: {registry_type}")

    # ── MCP Server handlers ──

    async def _resolve_unique_slug(self, repo: Any, name: str) -> str:
        """Workspace-scoped unique slug, using ``repo.get_by_slug`` for collision checks."""
        base = generate_slug(name)
        if await repo.get_by_slug(base) is None:
            return base
        for suffix in range(2, 1000):
            candidate = f"{base}-{suffix}"
            if await repo.get_by_slug(candidate) is None:
                return candidate
        raise ValueError(f"Exhausted collision suffixes (-2..-999) for slug base '{base}'")

    async def _create_mcp_server(self, item: RegistryItem, registry_url: str | None = None) -> str:
        spec = item.spec or {}
        conn_type = spec.get("connection_type", "url")
        docker_image_url, cmd = self._map_mcp_connection(conn_type, spec)
        remote_url = spec.get("url") if conn_type == "url" else None
        raw_spec = spec.get("raw_spec")
        tags = ["registry", conn_type]
        if spec.get("transport"):
            tags.append(spec["transport"])

        slug = await self._resolve_unique_slug(self.server_repo, item.name)

        server = await self.server_repo.create(
            name=item.name,
            slug=slug,
            description=item.description or "",
            docker_image_url=docker_image_url,
            version=item.version or "latest",
            tags=tags,
            is_public=False,
            env_schema=derive_env_schema_from_spec(spec),
            cmd=cmd,
            remote_url=remote_url,
            registry_item_id=item.id,
            json_spec=raw_spec,
            registry_url=registry_url,
        )
        return str(server.id)

    async def _update_mcp_server(self, item: RegistryItem, registry_url: str | None = None) -> Any:
        spec = item.spec or {}
        conn_type = spec.get("connection_type", "url")
        docker_image_url, cmd = self._map_mcp_connection(conn_type, spec)
        remote_url = spec.get("url") if conn_type == "url" else None
        raw_spec = spec.get("raw_spec")
        tags = ["registry", conn_type]
        if spec.get("transport"):
            tags.append(spec["transport"])

        if item.installed_entity_id is None:
            raise ValueError(f"Registry item {item.id} is not installed")

        return await self.server_repo.update(
            item.installed_entity_id,
            description=item.description or "",
            docker_image_url=docker_image_url,
            version=item.version or "latest",
            tags=tags,
            env_schema=derive_env_schema_from_spec(spec),
            cmd=cmd,
            remote_url=remote_url,
            json_spec=raw_spec,
            registry_url=registry_url,
        )

    async def _backfill_entity(
        self, registry_type: str, item: RegistryItem, registry_url: str | None = None
    ):
        """Update entity with json_spec/remote_url if missing."""
        if registry_type != "mcp_servers":
            return
        spec = item.spec or {}
        if spec.get("connection_type") == "openapi":
            return
        raw_spec = spec.get("raw_spec")
        if not raw_spec or not item.installed_entity_id:
            return
        conn_type = spec.get("connection_type", "url")
        remote_url = spec.get("url") if conn_type == "url" else None
        try:
            await self.server_repo.update(
                item.installed_entity_id,
                json_spec=raw_spec,
                remote_url=remote_url,
                registry_url=registry_url,
                env_schema=derive_env_schema_from_spec(spec),
            )
        except Exception:
            logger.debug("Backfill failed for %s", item.installed_entity_id, exc_info=True)

    @staticmethod
    def _map_mcp_connection(conn_type: str, spec: dict) -> tuple[str, list[str] | None]:
        docker_image_url = ""
        cmd = None
        if conn_type == "docker":
            docker_image_url = spec.get("image", "")
        elif conn_type == "command":
            docker_image_url = "agentarea/agentarea-mcp-base"
            command = spec.get("command", "")
            args = spec.get("args", [])
            cmd = [command, *args] if command else None
        return docker_image_url, cmd

    # ── Skill handlers ──

    async def _drop_platform_skill(self, item: RegistryItem) -> None:
        """Remove the platform Skill row a sync made before skills went catalog-only.

        Deleting through the repository also revokes the row's ownership in the
        authorization graph.
        """
        if not item.installed_entity_id:
            return
        if not self.skill_repo:
            raise ValueError("Skill repository not available")
        # Only a repository in the platform workspace sees those rows; through a
        # tenant's (an API-triggered sync) the delete would find nothing and the
        # link would be dropped while the row stays.
        if self.skill_repo.user_context.workspace_id != PLATFORM_WORKSPACE_ID:
            return
        await self.skill_repo.delete(item.installed_entity_id)
        item.installed_entity_id = None
        item.installed_version = None

    # ── LLM provider handlers ──

    async def _create_llm_provider(self, item: RegistryItem) -> str:
        if not self.provider_spec_repo:
            raise ValueError("Provider spec repository not available")
        from agentarea_llm.domain.models import ProviderSpec

        spec = item.spec or {}
        entity = ProviderSpec(
            provider_key=spec["provider_key"],
            name=item.name,
            description=item.description,
            provider_type=spec.get("provider_type", spec["provider_key"]),
            icon=spec.get("icon"),
            is_builtin=spec.get("is_builtin", True),
        )
        created = await self.provider_spec_repo.upsert_by_provider_key(entity)
        return str(created.id)

    async def _update_llm_provider(self, item: RegistryItem) -> Any:
        if not self.provider_spec_repo:
            raise ValueError("Provider spec repository not available")
        from agentarea_llm.domain.models import ProviderSpec

        spec = item.spec or {}
        entity = ProviderSpec(
            provider_key=spec["provider_key"],
            name=item.name,
            description=item.description,
            provider_type=spec.get("provider_type", spec["provider_key"]),
            icon=spec.get("icon"),
            is_builtin=spec.get("is_builtin", True),
        )
        return await self.provider_spec_repo.upsert_by_provider_key(entity)

    # ── LLM model handlers ──

    async def _resync_model_cache_prices(
        self, previous: dict[str, Any], current: dict[str, Any] | None
    ) -> None:
        """A model's cache prices, changed in the catalog, reach the workspaces' copies."""
        current = current or {}
        if not (self.model_spec_repo and self.provider_spec_repo):
            raise ValueError("Provider and model spec repositories required")
        provider = await self.provider_spec_repo.get_by_provider_key(current.get("provider_key"))
        if provider is None or not current.get("model_name"):
            return
        changed = await self.model_spec_repo.resync_cache_prices(
            provider_spec_id=provider.id,
            model_name=current["model_name"],
            previous=previous,
            current=current,
        )
        await self.model_spec_repo.session.commit()
        if changed:
            logger.info(
                "Catalog cache prices of %s/%s reached %d workspace copies",
                current.get("provider_key"),
                current["model_name"],
                changed,
            )

    async def _create_llm_model(self, item: RegistryItem) -> str:
        if not (self.model_spec_repo and self.provider_spec_repo):
            raise ValueError("Provider and model spec repositories required")
        spec = item.spec or {}
        provider = await self.provider_spec_repo.get_by_provider_key(spec["provider_key"])
        if not provider:
            raise ValueError(
                f"Provider '{spec['provider_key']}' not found; sync llm_providers registry first"
            )
        kind = ModelKind(spec.get("kind", ModelKind.CHAT))
        context_window = spec.get("context_window")
        if kind.priced_per_token:
            if (
                isinstance(context_window, bool)
                or not isinstance(context_window, int)
                or context_window <= 0
            ):
                raise ValueError(
                    f"Model '{spec['model_name']}' has no explicit positive context_window"
                )
            if spec.get("input_cost_per_token") is None:
                raise ValueError(
                    f"Model '{spec['model_name']}' has no explicit input_cost_per_token"
                )
            if spec.get("output_cost_per_token") is None:
                raise ValueError(
                    f"Model '{spec['model_name']}' has no explicit output_cost_per_token"
                )
        model = await self.model_spec_repo.upsert_by_provider_and_model_kwargs(
            provider_spec_id=provider.id,
            model_name=spec["model_name"],
            display_name=item.name,
            description=item.description,
            kind=kind.value,
            context_window=context_window,
            max_output_tokens=spec.get("max_output_tokens"),
            input_cost_per_token=to_optional_money(spec.get("input_cost_per_token")),
            output_cost_per_token=to_optional_money(spec.get("output_cost_per_token")),
            cached_input_cost_per_token=to_optional_money(spec.get("cached_input_cost_per_token")),
            cache_creation_input_cost_per_token=to_optional_money(
                spec.get("cache_creation_input_cost_per_token")
            ),
            supports_function_calling=spec.get("supports_function_calling", False),
            is_active=spec.get("is_active", True),
        )
        return str(model.id)

    async def _update_llm_model(self, item: RegistryItem) -> Any:
        return await self._create_llm_model(item)

    # ── Source fetching (format-agnostic) ──

    def _untrusted_client(self) -> httpx.AsyncClient:
        """For a member-supplied index: the pinned transport vets every hop's address."""
        return self.untrusted_client(
            follow_redirects=True,
            max_redirects=MAX_SOURCE_REDIRECTS,
            timeout=SOURCE_FETCH_TIMEOUT_SECONDS,
            headers={
                "Accept": "application/json, application/yaml, text/yaml",
                "User-Agent": "agentarea-registry-sync",
            },
        )

    async def _untrusted_etag(self, source_url: str) -> str | None:
        if urlsplit(source_url).scheme != "https":
            raise RegistrySourceError("the source is not a public https URL")
        try:
            async with asyncio.timeout(SOURCE_DEADLINE_SECONDS):
                async with self._untrusted_client() as client:
                    response = await client.head(source_url)
        except (httpx.HTTPError, TimeoutError):
            logger.warning("No ETag from a workspace source; reading it in full", exc_info=True)
            return None
        return response.headers.get("ETag") if response.status_code == 200 else None

    async def _fetch_untrusted(self, source_url: str) -> Any:
        """A workspace's index: https only, within a body cap and a deadline, no YAML aliases."""
        if urlsplit(source_url).scheme != "https":
            raise RegistrySourceError("the source is not a public https URL")
        body = bytearray()
        try:
            async with asyncio.timeout(SOURCE_DEADLINE_SECONDS):
                async with self._untrusted_client() as client:
                    async with client.stream("GET", source_url) as response:
                        if response.status_code != 200:
                            raise RegistrySourceError(
                                f"the source answered HTTP {response.status_code}"
                            )
                        async for chunk in response.aiter_bytes():
                            body += chunk
                            if len(body) > MAX_SOURCE_BYTES:
                                raise RegistrySourceError(
                                    f"the source is larger than {_size(MAX_SOURCE_BYTES)}"
                                )
        except TimeoutError as e:
            raise RegistrySourceError(
                f"the source took longer than {SOURCE_DEADLINE_SECONDS:g} s to read"
            ) from e
        except httpx.HTTPError as e:
            raise RegistrySourceError("the source could not be reached") from e
        return await asyncio.to_thread(_parse_untrusted, bytes(body))

    @staticmethod
    def _source_etag(source_url: str) -> str | None:
        """The source's current ETag; None for a local file or a host without one."""
        if not source_url.startswith(("http://", "https://")):
            return None
        req = urllib.request.Request(  # noqa: S310
            source_url, method="HEAD", headers={"User-Agent": "agentarea-registry-sync"}
        )
        try:
            with urllib.request.urlopen(  # noqa: S310
                req, timeout=SOURCE_FETCH_TIMEOUT_SECONDS, context=outbound_ssl_context()
            ) as resp:
                return resp.headers.get("ETag")
        except (urllib.error.HTTPError, urllib.error.URLError):
            # Some sources refuse HEAD (a presigned GET URL, an API without it);
            # without an ETag the source is read in full.
            logger.warning("No ETag from %s; reading it in full", source_url, exc_info=True)
            return None

    @staticmethod
    def _fetch_source(source_url: str) -> dict[str, Any]:
        """Fetch data from URL, auto-detect JSON vs YAML."""
        if source_url.startswith("http://") or source_url.startswith("https://"):
            req = urllib.request.Request(  # noqa: S310
                source_url,
                headers={
                    "Accept": "application/json, application/yaml, text/yaml, */*",
                    "User-Agent": "agentarea-registry-sync",
                },
            )
            with urllib.request.urlopen(  # noqa: S310
                req, timeout=SOURCE_FETCH_TIMEOUT_SECONDS, context=outbound_ssl_context()
            ) as resp:
                raw = resp.read().decode("utf-8")
                content_type = resp.headers.get("Content-Type", "")
        else:
            with open(source_url) as f:
                raw = f.read()
            content_type = ""

        if "yaml" in content_type or source_url.endswith((".yaml", ".yml")):
            return yaml.safe_load(raw)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return yaml.safe_load(raw)

    @staticmethod
    def _detect_type(data: Any) -> str:
        """Infer the registry type from a fetched catalog's top-level key."""
        if not isinstance(data, dict):
            raise ValueError("cannot detect registry type: source root is not a mapping")
        matched = [
            rtype for key, rtype in TYPE_BY_TOPLEVEL_KEY.items() if isinstance(data.get(key), list)
        ]
        if len(matched) == 1:
            return matched[0]
        if not matched:
            raise ValueError(
                "cannot detect registry type: expected one top-level key of "
                f"{list(TYPE_BY_TOPLEVEL_KEY)}"
            )
        raise ValueError(f"ambiguous registry type: multiple catalog keys present {matched}")

    @classmethod
    def detect_type_from_source(cls, source_url: str) -> str:
        """Fetch a source and infer its registry type from the payload shape."""
        return cls._detect_type(cls._fetch_source(source_url))

    # ── Source parsing (type-dispatched) ──

    @staticmethod
    def _parse_source(registry_type: str, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Catalog entries in publication order, each carrying its rank.

        Position *is* the curation signal -- the curated skills artifact is
        published in GitHub-star order, the connection artifact leads with the
        official integrations most workspaces want -- and nothing else in the
        payload expresses it. A parser that read an explicit rank keeps it.
        """
        items = RegistryService._parse_entries(registry_type, data)
        for position, item in enumerate(items):
            item.setdefault("recommendation_rank", position)
        return items

    @staticmethod
    def _parse_entries(registry_type: str, data: dict[str, Any]) -> list[dict[str, Any]]:
        if registry_type == "mcp_servers":
            return RegistryService._parse_mcp_servers(data)
        elif registry_type == "skills":
            return RegistryService._parse_skills(data)
        elif registry_type == "llm_providers":
            return RegistryService._parse_llm_providers(data)
        elif registry_type == "llm_models":
            return RegistryService._parse_llm_models(data)
        elif registry_type == "agents":
            return RegistryService._parse_agents(data)
        elif registry_type == "bundles":
            return RegistryService._parse_bundles(data)
        elif registry_type == "source_types":
            return RegistryService._parse_source_types(data)
        raise ValueError(f"Unknown registry_type: {registry_type}")

    @staticmethod
    def _parse_mcp_servers(data: dict[str, Any]) -> list[dict[str, Any]]:
        """Parse MCP servers from an official or AgentArea registry artifact.

        Standard format (registry.modelcontextprotocol.io):
            {"servers": [{"server": {"name": ..., "remotes": [...], "packages": [...]}, "_meta": {...}}]}

        AgentArea flattened format (published system catalog):
            {"servers": [{"registry_id": ..., "connection_type": ..., "json_spec": {...}}]}
        """
        servers = data.get("servers", [])
        if not servers:
            return []

        formats: set[str] = set()
        for index, entry in enumerate(servers):
            if not isinstance(entry, dict):
                raise ValueError(
                    "Unrecognized MCP registry format: each entry of 'servers' must be a mapping "
                    f"(entry {index} is {type(entry).__name__})"
                )
            if isinstance(entry.get("server"), dict):
                formats.add("standard")
            elif (
                isinstance(entry.get("registry_id"), str)
                and isinstance(entry.get("connection_type"), str)
                and isinstance(entry.get("json_spec"), dict)
            ):
                formats.add("agentarea")
            else:
                raise ValueError(
                    "Unrecognized MCP registry format: each entry of 'servers' must contain either "
                    "a mapping 'server' key or the AgentArea keys 'registry_id', "
                    f"'connection_type', and 'json_spec' (entry {index} keys: {sorted(entry)})"
                )

        if len(formats) != 1:
            raise ValueError(
                "Unrecognized MCP registry format: official and AgentArea entries cannot be mixed"
            )
        if "standard" in formats:
            return RegistryService._parse_standard_mcp_registry(servers)
        return RegistryService._parse_agentarea_mcp_registry(servers)

    @staticmethod
    def _parse_standard_mcp_registry(servers: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Parse official MCP registry format (remotes + packages)."""
        items = []
        for entry in servers:
            server = entry.get("server", {})
            meta = entry.get("_meta", {}).get("io.modelcontextprotocol.registry/official", {})

            # Only import latest versions
            if not meta.get("isLatest", True):
                continue

            identifier = server.get("name", "")
            if not identifier:
                continue

            title = server.get("title") or _humanize_identifier(identifier)
            description = (server.get("description") or "")[:500]
            version = server.get("version", "latest")
            # One server can publish a remote, an OCI package and a command;
            # they share the server's curated rank and break the tie on name.
            rank = rank_fields(server, server.get("metadata"))

            # Remote endpoints → connection_type: "url"
            for remote in server.get("remotes", []):
                transport = remote.get("type", "streamable-http")
                url = remote.get("url", "")
                if not url:
                    continue

                env_schema = normalize_env_schema(remote.get("headers", []))

                requires_auth = any(
                    h.get("name", "").lower() in ("authorization", "api_key", "x-api-key", "token")
                    for h in env_schema
                )

                tags = [transport]
                if requires_auth:
                    tags.append("requires-auth")

                items.append(
                    {
                        "external_id": identifier,
                        "name": title,
                        "description": description,
                        "version": version,
                        "spec": {
                            "connection_type": "url",
                            "url": url,
                            "transport": transport,
                            "env_schema": env_schema,
                            "raw_spec": server,
                        },
                        "tags": tags,
                        **rank,
                    }
                )

            # OCI packages → connection_type: "docker"
            for pkg in server.get("packages", []):
                if pkg.get("registryType") != "oci":
                    continue
                image = pkg.get("name", "") or pkg.get("identifier", "")
                pkg_version = pkg.get("version") or version
                if not image:
                    continue

                env_schema = normalize_env_schema(pkg.get("environmentVariables", []))

                items.append(
                    {
                        "external_id": f"{identifier}/docker",
                        "name": title,
                        "description": description,
                        "version": pkg_version,
                        "spec": {
                            "connection_type": "docker",
                            "image": f"{image}:{pkg_version}" if ":" not in image else image,
                            "transport": "stdio",
                            "env_schema": env_schema,
                            "package_registry": "oci",
                            "package_name": pkg.get("name", "") or pkg.get("identifier", ""),
                            "raw_spec": server,
                        },
                        "tags": ["docker", "oci"],
                        **rank,
                    }
                )

            # npm/pypi/nuget/mcpb packages → connection_type: "command"
            for pkg in server.get("packages", []):
                reg_type = pkg.get("registryType", "")
                if reg_type not in ("npm", "pypi", "nuget", "mcpb"):
                    continue
                pkg_name = pkg.get("name", "") or pkg.get("identifier", "")
                pkg_version = pkg.get("version") or version
                if not pkg_name:
                    continue

                resolved_command = _command_package_args(pkg, reg_type, version)
                if resolved_command is None:
                    continue
                command, args = resolved_command

                env_schema = normalize_env_schema(pkg.get("environmentVariables", []))

                items.append(
                    {
                        "external_id": f"{identifier}/command",
                        "name": title,
                        "description": description,
                        "version": pkg_version,
                        "spec": {
                            "connection_type": "command",
                            "command": command,
                            "args": args,
                            "transport": "stdio",
                            "package_registry": reg_type,
                            "package_name": pkg_name,
                            "env_schema": env_schema,
                            "raw_spec": server,
                        },
                        "tags": ["command", reg_type],
                        **rank,
                    }
                )

        return items

    @staticmethod
    def _parse_agentarea_mcp_registry(servers: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Parse the normalized format published by the AgentArea catalog pipeline."""
        items = []
        for entry in servers:
            external_id = entry["registry_id"]
            connection_type = entry["connection_type"]
            json_spec = entry["json_spec"]

            item_external_id = (
                f"{external_id}/{connection_type}" if connection_type != "url" else external_id
            )

            tags = []
            if entry.get("package_registry"):
                tags.append(entry["package_registry"])
            if entry.get("requires_auth"):
                tags.append("requires-auth")
            transport = entry.get("transport") or json_spec.get("transport", "")
            if transport:
                tags.append(transport)

            spec = {**json_spec, "connection_type": connection_type}
            if entry.get("env_schema"):
                spec["env_schema"] = normalize_env_schema(entry["env_schema"])
            elif "env_schema" in spec:
                spec["env_schema"] = normalize_env_schema(spec["env_schema"])
            else:
                derived_schema = derive_env_schema_from_spec(spec)
                if derived_schema:
                    spec["env_schema"] = derived_schema

            items.append(
                {
                    "external_id": item_external_id,
                    "name": entry.get("name") or external_id,
                    "description": (entry.get("description") or "")[:500],
                    "version": entry.get("version") or "latest",
                    "spec": spec,
                    "tags": tags,
                    **rank_fields(entry),
                }
            )
        return items

    @staticmethod
    def _parse_skills(data: dict[str, Any]) -> list[dict[str, Any]]:
        skills = data.get("skills", [])
        items = []
        for entry in skills:
            name = entry.get("name", "")
            if not name:
                continue
            source = RegistryService._skill_source(name, entry.get("source"))
            if source is None:
                source_url = entry.get("source_url")
                spec = {
                    "source_type": entry.get("source_type", "content"),
                    "content": entry.get("content"),
                    # Rendered as a link: an index may not hand the UI a script URL.
                    "source_url": (
                        source_url
                        if isinstance(source_url, str) and source_url.startswith("https://")
                        else None
                    ),
                }
                version = entry.get("version") or "1.0.0"
            else:
                # The platform index (ADR-0044) carries a pointer, not a body:
                # the folder's tree SHA is the content's identity.
                folder = f"/{source['path']}" if source["path"] else ""
                spec = {
                    "source_type": "github",
                    "source": source,
                    "source_url": (
                        f"https://github.com/{source['repo']}/tree/"
                        f"{source.get('ref', 'HEAD')}{folder}"
                    ),
                }
                version = source.get("tree_sha") or "latest"
                if "provenance" not in entry:
                    entry = {
                        **entry,
                        "provenance": {
                            "repo": source["repo"],
                            "path": source["path"],
                            **{k: entry[k] for k in ("stars", "license") if k in entry},
                        },
                    }
            original_name = entry.get("original_name")
            if isinstance(original_name, str) and original_name:
                spec["original_name"] = original_name

            raw_provenance = entry.get("provenance")
            if isinstance(raw_provenance, dict):
                provenance = {
                    key: raw_provenance[key]
                    for key in (
                        "repo",
                        "path",
                        "branch",
                        "stars",
                        "license",
                        "distribution",
                        "source",
                        "duplicate_count",
                    )
                    if key in raw_provenance
                }
                if provenance:
                    spec["provenance"] = provenance
            items.append(
                {
                    "external_id": name,
                    "name": name,
                    "description": entry.get("description"),
                    "version": version,
                    "spec": spec,
                    "tags": entry.get("tags", []),
                    **rank_fields(entry),
                }
            )
        return items

    @staticmethod
    def _skill_source(name: str, raw: Any) -> dict[str, str] | None:
        """The GitHub pointer of a platform-index skill, or ``None`` for an inline one.

        A malformed pointer fails the whole parse: the sync then leaves the last
        snapshot in place and records why, instead of publishing a skill that
        cannot be installed.
        """
        if raw is None:
            return None
        if not isinstance(raw, dict) or raw.get("type") != "github":
            raise ValueError(f"skill {name!r}: source must be a mapping with type 'github'")
        repo, path = raw.get("repo"), raw.get("path", "")
        if (
            not isinstance(repo, str)
            or not _GITHUB_REPO.fullmatch(repo)
            or {".", ".."} & set(repo.split("/"))
        ):
            raise ValueError(f"skill {name!r}: source.repo must be 'owner/name', got {repo!r}")
        path = path.strip("/") if isinstance(path, str) else None
        if path is None or (path and {"", ".", ".."} & set(path.split("/"))):
            raise ValueError(f"skill {name!r}: source.path must be a plain relative path")
        source = {"type": "github", "repo": repo, "path": path}
        for key in ("ref", "tree_sha"):
            value = raw.get(key)
            if value is None:
                continue
            if not isinstance(value, str) or not _GIT_SHA.fullmatch(value):
                raise ValueError(f"skill {name!r}: source.{key} must be a 40-hex git sha")
            source[key] = value
        return source

    @staticmethod
    def _parse_llm_providers(data: dict[str, Any]) -> list[dict[str, Any]]:
        providers = data.get("providers", [])
        items = []
        for entry in providers:
            provider_key = entry.get("provider_key")
            if not provider_key:
                continue
            items.append(
                {
                    "external_id": provider_key,
                    "name": entry.get("name") or provider_key,
                    "description": entry.get("description"),
                    "version": entry.get("version") or "1.0.0",
                    "spec": {
                        "provider_key": provider_key,
                        "provider_type": entry.get("provider_type", provider_key),
                        "icon": entry.get("icon"),
                        "is_builtin": entry.get("is_builtin", True),
                    },
                    "tags": entry.get("tags", []),
                }
            )
        return items

    @staticmethod
    def _parse_llm_models(data: dict[str, Any]) -> list[dict[str, Any]]:
        models = data.get("models", [])
        items = []
        for entry in models:
            provider_key = entry.get("provider_key")
            model_name = entry.get("model_name")
            if not provider_key or not model_name:
                continue
            kind = entry.get("kind", ModelKind.CHAT)
            if kind not in _MODEL_KINDS:
                raise ValueError(
                    f"Model '{provider_key}/{model_name}' has unknown kind {kind!r}; "
                    f"expected one of {', '.join(_MODEL_KINDS)}"
                )
            items.append(
                {
                    "external_id": f"{provider_key}/{model_name}",
                    "name": entry.get("display_name") or model_name,
                    "description": entry.get("description"),
                    "version": entry.get("version") or "1.0.0",
                    "spec": {
                        "provider_key": provider_key,
                        "model_name": model_name,
                        "kind": kind,
                        "context_window": entry.get("context_window"),
                        "max_output_tokens": entry.get("max_output_tokens"),
                        "input_cost_per_token": entry.get("input_cost_per_token"),
                        "output_cost_per_token": entry.get("output_cost_per_token"),
                        "cached_input_cost_per_token": entry.get("cached_input_cost_per_token"),
                        "cache_creation_input_cost_per_token": entry.get(
                            "cache_creation_input_cost_per_token"
                        ),
                        "supports_function_calling": entry.get("supports_function_calling", False),
                        "is_active": entry.get("is_active", True),
                    },
                    "tags": entry.get("tags", []),
                }
            )
        return items

    @staticmethod
    def _parse_agents(data: dict[str, Any]) -> list[dict[str, Any]]:
        agents = data.get("agents", [])
        items = []
        for entry in agents:
            name = entry.get("name")
            if not name:
                continue
            agent_id = entry.get("id")
            tools = entry.get("tools") or []
            if not isinstance(tools, list):
                tools = []
            items.append(
                {
                    "external_id": str(agent_id) if agent_id else name,
                    "name": name,
                    "description": entry.get("description"),
                    "version": entry.get("version") or "1.0.0",
                    "spec": {
                        "id": agent_id,
                        "name": name,
                        "description": entry.get("description"),
                        "instruction": entry.get("instruction", ""),
                        # Catalog is global; model instances are per-workspace. Carry
                        # model *preferences* (slugs, priority order) — never a concrete
                        # ``model_id`` (instance UUID), which is resolved per workspace
                        # at install time.
                        "preferred_models": _agent_preferred_models(entry),
                        "tools": tools,
                        "planning": entry.get("planning", False),
                        # Presets name catalog skills by their stable key and
                        # carry trigger templates; see the agent presets API.
                        "skills": entry.get("skills") or [],
                        "triggers": entry.get("triggers") or [],
                    },
                    "tags": entry.get("tags", []),
                    **rank_fields(entry),
                }
            )
        return items

    @staticmethod
    def _parse_source_types(data: dict[str, Any]) -> list[dict[str, Any]]:
        """Event source types (ADR-0040): the whole entry is the spec, its slug the external id."""
        items = []
        for entry in data.get("source_types", []):
            slug = entry.get("slug")
            if not slug:
                raise ValueError(f"source type entry {entry.get('name')!r} has no slug")
            items.append(
                {
                    "external_id": slug,
                    "name": entry.get("name") or slug,
                    "description": (entry.get("description") or "")[:500],
                    "version": entry.get("version") or "1.0.0",
                    "spec": entry,
                    "tags": [entry.get("delivery")] if entry.get("delivery") else [],
                    **rank_fields(entry),
                }
            )
        return items

    @staticmethod
    def _parse_bundles(data: dict[str, Any]) -> list[dict[str, Any]]:
        """Parse installable bundles.

        Each catalog entry IS a canonical Bundle (the same shape the
        ``/v1/bundles/install`` endpoint consumes). The whole entry is stored as
        the registry_item ``spec`` so install can run against it unchanged;
        ``external_id`` is the bundle ``name`` (its idempotency key).
        """
        items = []
        for entry in data.get("bundles", []):
            name = entry.get("name")
            if not name:
                continue
            metadata = entry.get("metadata") or {}
            tags = entry.get("tags") or metadata.get("capabilities") or []
            if not isinstance(tags, list):
                tags = []
            items.append(
                {
                    "external_id": name,
                    "name": entry.get("display_name") or name,
                    "description": entry.get("description"),
                    "version": entry.get("schema_version") or entry.get("version") or "0.1.0",
                    "spec": entry,
                    "tags": tags,
                    **rank_fields(entry, metadata),
                }
            )
        return items


# ModelKind values; a catalog file names them as strings.
_MODEL_KINDS = tuple(kind.value for kind in ModelKind)


def _agent_preferred_models(entry: dict[str, Any]) -> list[str]:
    """Extract a catalog agent's preferred model slugs in priority order."""
    preferred = entry.get("preferred_models")
    if isinstance(preferred, list):
        return [m for m in preferred if isinstance(m, str) and m]
    return []


def _humanize_identifier(identifier: str) -> str:
    """Convert registry identifier to a human-readable name.

    Examples:
        'ai.aliengiraffe/spotdb'     → 'Spotdb'
        'com.github/copilot-mcp'     → 'Copilot MCP'
        'agency.lona/trading'        → 'Trading'
    """
    # Take the part after the last slash
    if "/" in identifier:
        name = identifier.rsplit("/", 1)[-1]
    else:
        name = identifier

    # Known abbreviations to keep uppercase
    abbrevs = {"mcp", "api", "ai", "db", "sql", "ssh", "aws", "gcp", "cli", "sdk", "llm"}

    parts = name.replace("-", " ").replace("_", " ").split()
    return " ".join(p.upper() if p.lower() in abbrevs else p.capitalize() for p in parts)
