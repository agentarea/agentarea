"""Outbound-URL SSRF guard.

Validation barrier for HTTP requests whose URL is influenced by user input
(e.g. BYOK LLM provider ``endpoint_url``, MCP upstream proxies). It rejects the
universal IANA non-public address classes so it stays portable across clouds and
hardcodes no provider-specific IPs: RFC1918 private, loopback, link-local
(blocks ``169.254.169.254`` cloud metadata on every provider), reserved,
multicast and unspecified addresses.

This is the code layer of a two-layer SSRF defense. The rebinding-proof,
topology-aware layer is the per-cluster egress network policy; see the wiki page
``operations/enterprise-deployment-hardening`` in the agentarea-wiki repo.

``validate_outbound_url`` is a pre-check only: it resolves the name once and the
HTTP client resolves it again, so a rebinding name can pass it. A request to a
member-supplied URL goes through ``safe_async_client``, whose transport resolves,
vets and pins the address for the connection itself, on every redirect hop.
"""

import asyncio
import fnmatch
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx

__all__ = [
    "OutboundPolicy",
    "PinnedSender",
    "Resolver",
    "SafeOutboundTransport",
    "UnsafeDestinationError",
    "UnsafeUrlError",
    "resolve_host",
    "safe_async_client",
    "validate_outbound_url",
]

_ALLOWED_SCHEMES = frozenset({"http", "https"})

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


class UnsafeUrlError(ValueError):
    """Raised when a URL is not safe to request (bad scheme or non-public host)."""


class UnsafeDestinationError(httpx.RequestError, UnsafeUrlError):
    """A request the pinned client refused to send.

    An ``httpx.RequestError`` so callers that already treat "could not reach
    the host" as a failed fetch handle it the same way.
    """


def _host_in_allowlist(host: str, allowed_hosts: Iterable[str]) -> bool:
    """Case-insensitive glob match of ``host`` against allowlist patterns.

    Patterns are host/FQDN globs, e.g. ``api.github.com`` or ``*.github.com``.
    An empty allowlist matches nothing (default-deny).
    """
    host_lower = host.lower()
    return any(fnmatch.fnmatch(host_lower, pattern.lower()) for pattern in allowed_hosts)


def _is_blocked_ip(ip: IPAddress) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
        # Shared address space (100.64.0.0/10) and the other special-purpose
        # ranges; some clouds serve instance metadata from there.
        or not ip.is_global
    )


def validate_outbound_url(
    url: str,
    *,
    allow_private: bool = False,
    allowed_hosts: Iterable[str] | None = None,
    policy: "OutboundPolicy | None" = None,
) -> None:
    """Validate that ``url`` is safe to fetch; raise ``UnsafeUrlError`` otherwise.

    Enforces an http/https scheme and, unless ``allow_private`` is set, resolves
    the host and rejects it if any resolved address is in a non-public class.

    ``allow_private`` is the self-host opt-out for installs that legitimately
    target private endpoints (e.g. a custom on-LAN Ollama). Keep it ``False`` for
    hosted/multi-tenant deployments.

    ``allowed_hosts`` is the egress allowlist for the cases the platform makes the
    request itself (url-type MCP, BYOK endpoints): when provided, the host must
    glob-match at least one pattern (e.g. ``*.github.com``) or the request is
    refused. ``None`` disables allowlist filtering (backwards-compatible default);
    an empty iterable means default-deny. Container-hosted MCPs egress out of the
    platform's sight — those are enforced by the enterprise EgressEnforcer, not
    here.

    ``policy``, when given, replaces ``allow_private``: the check then admits
    exactly what ``safe_async_client`` with that policy would connect to.
    """
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise UnsafeUrlError(f"URL scheme {parts.scheme!r} is not allowed; use http or https")

    host = parts.hostname
    if not host:
        raise UnsafeUrlError("URL has no host")

    if allowed_hosts is not None and not _host_in_allowlist(host, allowed_hosts):
        raise UnsafeUrlError(f"URL host {host!r} is not in the egress allowlist; refusing request")

    if policy.allow_private if policy is not None else allow_private:
        return

    port = parts.port or (443 if scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"Could not resolve host {host!r}") from exc

    for info in infos:
        # info[4] is the sockaddr; its first element is the address string. Cast
        # for the type checker (the stub types the tuple element as str | int).
        addr = str(info[4][0]).split("%")[0]  # strip IPv6 zone id (e.g. fe80::1%eth0)
        ip = ipaddress.ip_address(addr)
        blocked = _is_blocked_ip(ip) if policy is None else not policy.permits(host, ip)
        if blocked:
            raise UnsafeUrlError(
                f"URL host {host!r} resolves to non-public address {ip}; refusing request"
            )


@dataclass(frozen=True)
class OutboundPolicy:
    """Which non-public destinations a member-supplied URL may still reach.

    ``private_allowlist`` holds host globs (``localhost``, ``*.svc.cluster.local``)
    and CIDRs (``192.168.1.0/24``) for deployments that legitimately target a
    private endpoint, such as a local Ollama. ``allow_private`` is the existing
    blanket opt-out (``ALLOW_PRIVATE_URLS``). Both default to closed.
    """

    allow_private: bool = False
    private_allowlist: tuple[str, ...] = ()
    _networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = field(
        init=False, repr=False, compare=False
    )
    _host_patterns: tuple[str, ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Split the allowlist into CIDRs and host globs; a malformed CIDR raises."""
        networks = []
        patterns = []
        for entry in self.private_allowlist:
            if "/" in entry:
                networks.append(ipaddress.ip_network(entry, strict=False))
            else:
                patterns.append(entry.lower())
        object.__setattr__(self, "_networks", tuple(networks))
        object.__setattr__(self, "_host_patterns", tuple(patterns))

    @classmethod
    def from_env(cls) -> "OutboundPolicy":
        from agentarea_common.config.app import AppSettings
        from agentarea_common.config.mcp import MCPSettings

        raw = AppSettings().OUTBOUND_PRIVATE_ALLOWLIST
        return cls(
            allow_private=MCPSettings().ALLOW_PRIVATE_URLS,
            private_allowlist=tuple(e.strip() for e in raw.split(",") if e.strip()),
        )

    def permits(self, host: str, ip: IPAddress) -> bool:
        if not _is_blocked_ip(ip) or self.allow_private:
            return True
        if any(fnmatch.fnmatch(host.lower(), pattern) for pattern in self._host_patterns):
            return True
        return any(ip in network for network in self._networks)


Resolver = Callable[[str, int], Awaitable[list[str]]]


async def resolve_host(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]).split("%")[0] for info in infos]


class PinnedSender:
    """Resolve, vet and pin one request, for any client speaking the httpx API.

    ``lib`` is the module whose ``Request`` and ``AsyncHTTPTransport`` the caller
    uses: ``httpx`` here, ``httpx2`` for the MCP SDK's client. ``error`` is raised
    for a refused destination and should be that library's ``RequestError`` so
    its callers treat it as an unreachable host.

    The request goes to the vetted IP, with the original name kept in the Host
    header and as the TLS server name, so a name cannot resolve to one address
    when vetted and another when connected.
    """

    def __init__(
        self,
        lib: Any,
        policy: OutboundPolicy,
        *,
        error: Callable[..., Exception],
        resolve: Resolver = resolve_host,
        inner: Any = None,
    ) -> None:
        self._lib = lib
        self._policy = policy
        self._error = error
        self._resolve = resolve
        self._inner = inner or lib.AsyncHTTPTransport(trust_env=False)

    async def send(self, request: Any) -> Any:
        url = request.url
        if url.scheme not in _ALLOWED_SCHEMES:
            raise self._error(f"URL scheme {url.scheme!r} is not allowed", request=request)
        host = url.host
        if not host:
            raise self._error("URL has no host", request=request)

        try:
            addresses = [ipaddress.ip_address(host)]
        except ValueError:
            port = url.port or (443 if url.scheme == "https" else 80)
            try:
                resolved = await self._resolve(host, port)
            except OSError as exc:
                raise self._error(f"Could not resolve host {host!r}", request=request) from exc
            addresses = [ipaddress.ip_address(addr) for addr in resolved]
        if not addresses:
            raise self._error(f"Host {host!r} has no address", request=request)
        for ip in addresses:
            if not self._policy.permits(host, ip):
                raise self._error(
                    f"URL host {host!r} resolves to non-public address {ip}; refusing request",
                    request=request,
                )

        extensions: dict[str, Any] = dict(request.extensions)
        if url.scheme == "https" and str(addresses[0]) != host:
            extensions.setdefault("sni_hostname", host)
        pinned = self._lib.Request(
            request.method,
            url.copy_with(host=str(addresses[0])),
            headers=request.headers,
            stream=request.stream,
            extensions=extensions,
        )
        return await self._inner.handle_async_request(pinned)

    async def aclose(self) -> None:
        await self._inner.aclose()


class SafeOutboundTransport(httpx.AsyncBaseTransport):
    """Sends each request only to an address it resolved and vetted itself.

    The client hands every redirect hop back through here, so each hop is
    vetted the same way.
    """

    def __init__(
        self,
        policy: OutboundPolicy,
        *,
        resolve: Resolver = resolve_host,
        inner: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._sender = PinnedSender(
            httpx, policy, error=UnsafeDestinationError, resolve=resolve, inner=inner
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self._sender.send(request)

    async def aclose(self) -> None:
        await self._sender.aclose()


def safe_async_client(*, policy: OutboundPolicy | None = None, **kwargs: Any) -> httpx.AsyncClient:
    """``httpx.AsyncClient`` for a URL a member supplied, directly or via a document.

    Takes the ``httpx.AsyncClient`` keyword arguments except ``transport``.
    """
    transport = SafeOutboundTransport(policy or OutboundPolicy.from_env())
    return httpx.AsyncClient(transport=transport, **kwargs)
