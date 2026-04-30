"""Service layer for OpenAPI connection management."""

import json
import logging
from typing import Any
from uuid import UUID, uuid4

import httpx
import yaml
from agentarea_common.infrastructure.secret_manager import BaseSecretManager

from agentarea_openapi.application.spec_parser import parse_openapi_spec
from agentarea_openapi.application.url_validator import (
    _SPEC_MAX_SIZE,
    build_pinned_target,
    validate_url,
)
from agentarea_openapi.domain.models import OpenAPIConnection
from agentarea_openapi.infrastructure.repository import OpenAPIConnectionRepository
from agentarea_openapi.schemas.dto import (
    OpenAPIConnectionCreate,
    OpenAPIConnectionUpdate,
)

logger = logging.getLogger(__name__)

# Headers that are never sensitive — stored as plaintext.
_SAFE_HEADERS = frozenset(
    h.lower()
    for h in (
        "Accept",
        "Accept-Charset",
        "Accept-Encoding",
        "Accept-Language",
        "Cache-Control",
        "Content-Type",
        "If-Match",
        "If-None-Match",
        "User-Agent",
        "X-Correlation-ID",
        "X-Request-ID",
    )
)


def _secret_key(connection_id: str | UUID, header_name: str) -> str:
    """Build the secret manager key for a header value."""
    return f"openapi:{connection_id}:header:{header_name}"


def _is_safe_header(name: str) -> bool:
    return name.lower() in _SAFE_HEADERS


async def fetch_and_parse_spec(
    url: str,
    *,
    allow_private: bool = False,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Fetch an OpenAPI spec from a URL with SSRF protection and streaming size check.

    Shared by service._fetch_spec and the preview_spec endpoint.

    Raises:
        ValueError: On validation failure, size limit, or fetch error.
        httpx.HTTPStatusError: On non-2xx response.
    """
    resolved_ips = validate_url(url, allow_private=allow_private)

    # SSRF defenses: validate_url has confirmed scheme ∈ {http,https} and that
    # every resolved address is non-private (or allow_private). build_pinned_target
    # returns the destination identifiers (scheme/host/port) and the path/query as
    # separate, validated fields so the HTTP sink never receives a single string
    # that mixes user-controlled path data into the destination.
    target = build_pinned_target(url, resolved_ips[0] if resolved_ips else None)

    request_headers = dict(headers or {})
    if target.original_host:
        request_headers.setdefault("Host", target.original_host)

    # Construct the request URL from the validated components. scheme/host come
    # from sanitized values (literal scheme + resolved-and-vetted IP); the path
    # only addresses a resource on that already-vetted destination.
    fetch_url = httpx.URL(
        scheme=target.scheme,
        host=target.host,
        port=target.port,
        path=target.path,
        query=target.raw_query,
    )

    # We connect to a pinned IP (anti-DNS-rebinding) but the TLS cert is issued
    # for the original hostname — pass sni_hostname so SNI + cert validation use
    # the original host instead of the IP we connect to.
    extensions = {"sni_hostname": target.original_host} if target.original_host else None

    async with httpx.AsyncClient(
        timeout=30, headers=request_headers, follow_redirects=False, verify=True
    ) as client:
        async with client.stream("GET", fetch_url, extensions=extensions) as resp:
            resp.raise_for_status()
            chunks: list[bytes] = []
            total = 0
            async for chunk in resp.aiter_bytes(chunk_size=64 * 1024):
                total += len(chunk)
                if total > _SPEC_MAX_SIZE:
                    raise ValueError("Spec response exceeds 5MB limit.")
                chunks.append(chunk)

    content = b"".join(chunks)
    text = content.decode(resp.encoding or "utf-8", errors="replace")

    if url.endswith((".yaml", ".yml")):
        return yaml.safe_load(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return yaml.safe_load(text)


class OpenAPIConnectionService:
    def __init__(
        self,
        repository_factory: Any,
        secret_manager: BaseSecretManager,
        allow_private_urls: bool = False,
    ) -> None:
        self._repo: OpenAPIConnectionRepository = repository_factory.create_repository(
            OpenAPIConnectionRepository
        )
        self._secret_manager = secret_manager
        self._allow_private_urls = allow_private_urls

    async def create_connection(self, payload: OpenAPIConnectionCreate) -> OpenAPIConnection:
        # Validate URLs at creation time (SSRF protection)
        validate_url(payload.base_url, allow_private=self._allow_private_urls)
        if payload.spec_url:
            validate_url(payload.spec_url, allow_private=self._allow_private_urls)

        # Pre-generate ID so secrets can be stored atomically
        conn_id = uuid4()

        processed_headers = None
        if payload.custom_headers:
            raw_headers = [h.model_dump() for h in payload.custom_headers]
            processed_headers = await self._store_headers(raw_headers, connection_id=conn_id)

        # Eagerly resolve spec + tools so callers get a ready-to-use connection
        # in a single request. Pasted JSON is parsed in-place; spec_url is fetched.
        resolved_spec: dict[str, Any] | None = payload.spec_content
        if resolved_spec is None and payload.spec_url:
            resolved_headers = {
                h["name"]: h.get("value", "")
                for h in (processed_headers or [])
                if not h.get("secret") and h.get("value")
            }
            # Secret headers resolved below via resolve_headers once conn exists;
            # for initial fetch, non-secret headers are enough for most public specs.
            resolved_spec = await fetch_and_parse_spec(
                payload.spec_url,
                allow_private=self._allow_private_urls,
                headers=resolved_headers or None,
            )

        available_tools: list[dict[str, Any]] = []
        if resolved_spec is not None:
            available_tools = parse_openapi_spec(resolved_spec)

        conn = await self._repo.create(
            id=conn_id,
            name=payload.name,
            base_url=payload.base_url,
            description=payload.description,
            spec_url=payload.spec_url,
            spec_content=resolved_spec,
            auth_config_id=payload.auth_config_id,
            custom_headers=processed_headers,
            available_tools=available_tools,
        )

        return conn

    async def _store_headers(
        self,
        raw_headers: list[dict[str, str]],
        connection_id: str | UUID,
    ) -> list[dict[str, Any]]:
        """Classify headers and store secret values.

        Input: [{"name": "Authorization", "value": "Bearer xxx"}, ...]
        Output: [{"name": "Authorization", "secret": true}, ...]
        """
        processed = []
        for h in raw_headers:
            header_name = h.get("name", "").strip()
            header_value = h.get("value", "")
            if not header_name:
                continue

            is_secret = not _is_safe_header(header_name)
            entry: dict[str, Any] = {"name": header_name, "secret": is_secret}

            if is_secret:
                if header_value:
                    key = _secret_key(connection_id, header_name)
                    await self._secret_manager.set_secret(key, header_value)
                # Don't store secret value in DB
            else:
                entry["value"] = header_value

            processed.append(entry)
        return processed

    async def update_headers(
        self,
        connection_id: UUID,
        raw_headers: list[dict[str, str]],
    ) -> OpenAPIConnection | None:
        """Replace all custom headers on a connection."""
        conn = await self._repo.get_by_id(str(connection_id))
        if not conn:
            return None

        # Clean up old secrets
        await self._delete_header_secrets(conn)

        processed = await self._store_headers(raw_headers, connection_id)
        return await self._repo.update(str(connection_id), custom_headers=processed)

    async def _delete_header_secrets(self, conn: OpenAPIConnection) -> None:
        """Remove all secret header values from the secret manager."""
        if not conn.custom_headers:
            return
        for h in conn.custom_headers:
            if h.get("secret"):
                key = _secret_key(conn.id, h["name"])
                try:
                    await self._secret_manager.delete_secret(key)
                except Exception:
                    logger.warning(f"Failed to delete secret for header {h['name']}")

    async def resolve_headers(self, conn: OpenAPIConnection) -> dict[str, str]:
        """Build the actual HTTP headers dict by resolving secrets."""
        if not conn.custom_headers:
            return {}

        headers: dict[str, str] = {}
        for h in conn.custom_headers:
            name = h["name"]
            if h.get("secret"):
                if self._secret_manager:
                    value = await self._secret_manager.get_secret(_secret_key(conn.id, name))
                    if value:
                        headers[name] = value
            else:
                value = h.get("value", "")
                if value:
                    headers[name] = value
        return headers

    async def get_connection(self, connection_id: UUID) -> OpenAPIConnection | None:
        return await self._repo.get_by_id(str(connection_id))

    async def list_connections(
        self,
        status: str | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[OpenAPIConnection], int]:
        return await self._repo.list_connections(
            status=status, search=search, limit=limit, offset=offset
        )

    async def update_connection(
        self,
        connection_id: UUID,
        payload: OpenAPIConnectionUpdate,
    ) -> OpenAPIConnection | None:
        """Apply a partial update. Headers are processed separately so secrets stay atomic."""
        patch = payload.model_dump(exclude_unset=True)

        # custom_headers are routed through update_headers (secret manager).
        if "custom_headers" in patch:
            raw_headers = patch.pop("custom_headers")
            if raw_headers is not None:
                conn = await self.update_headers(connection_id, raw_headers)
                if not conn:
                    return None

        # Validate URLs on update (SSRF protection)
        if patch.get("base_url"):
            validate_url(patch["base_url"], allow_private=self._allow_private_urls)
        if patch.get("spec_url"):
            validate_url(patch["spec_url"], allow_private=self._allow_private_urls)

        if patch:
            return await self._repo.update(str(connection_id), **patch)

        # No non-header fields — return current state (post-header-update or untouched).
        return await self._repo.get_by_id(str(connection_id))

    async def delete_connection(self, connection_id: UUID) -> bool:
        conn = await self._repo.get_by_id(str(connection_id))
        if conn:
            await self._delete_header_secrets(conn)
        return await self._repo.delete(str(connection_id))

    async def discover_tools(self, connection_id: UUID) -> dict[str, Any]:
        """Fetch/parse the OpenAPI spec and store discovered tools."""
        conn = await self._repo.get_by_id(str(connection_id))
        if not conn:
            raise ValueError(f"Connection {connection_id} not found")

        spec = conn.spec_content
        if not spec:
            spec = await self._fetch_spec(conn)

        tools = parse_openapi_spec(spec)

        await self._repo.update(str(conn.id), available_tools=tools, spec_content=spec)
        conn = await self._repo.get_by_id(str(conn.id))

        return {
            "connection_id": str(conn.id),
            "tools_discovered": len(tools),
            "tools": [{"name": t["name"], "description": t["description"]} for t in tools],
        }

    async def _fetch_spec(self, conn: OpenAPIConnection) -> dict[str, Any]:
        """Fetch OpenAPI spec from spec_url."""
        if not conn.spec_url:
            raise ValueError(
                f"No spec_url or spec_content for connection {conn.name}. "
                "Provide a spec_url or upload spec_content."
            )

        headers = await self.resolve_headers(conn)
        return await fetch_and_parse_spec(
            conn.spec_url,
            allow_private=self._allow_private_urls,
            headers=headers,
        )
