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
"""

import fnmatch
import ipaddress
import socket
from collections.abc import Iterable
from urllib.parse import urlsplit

__all__ = ["UnsafeUrlError", "validate_outbound_url"]

_ALLOWED_SCHEMES = frozenset({"http", "https"})


class UnsafeUrlError(ValueError):
    """Raised when a URL is not safe to request (bad scheme or non-public host)."""


def _host_in_allowlist(host: str, allowed_hosts: Iterable[str]) -> bool:
    """Case-insensitive glob match of ``host`` against allowlist patterns.

    Patterns are host/FQDN globs, e.g. ``api.github.com`` or ``*.github.com``.
    An empty allowlist matches nothing (default-deny).
    """
    host_lower = host.lower()
    return any(fnmatch.fnmatch(host_lower, pattern.lower()) for pattern in allowed_hosts)


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def validate_outbound_url(
    url: str,
    *,
    allow_private: bool = False,
    allowed_hosts: Iterable[str] | None = None,
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

    if allow_private:
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
        if _is_blocked_ip(ip):
            raise UnsafeUrlError(
                f"URL host {host!r} resolves to non-public address {ip}; refusing request"
            )
