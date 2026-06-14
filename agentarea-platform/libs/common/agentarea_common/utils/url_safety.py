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

import ipaddress
import socket
from urllib.parse import urlsplit

__all__ = ["UnsafeUrlError", "validate_outbound_url"]

_ALLOWED_SCHEMES = frozenset({"http", "https"})


class UnsafeUrlError(ValueError):
    """Raised when a URL is not safe to request (bad scheme or non-public host)."""


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def validate_outbound_url(url: str, *, allow_private: bool = False) -> None:
    """Validate that ``url`` is safe to fetch; raise ``UnsafeUrlError`` otherwise.

    Enforces an http/https scheme and, unless ``allow_private`` is set, resolves
    the host and rejects it if any resolved address is in a non-public class.

    ``allow_private`` is the self-host opt-out for installs that legitimately
    target private endpoints (e.g. a custom on-LAN Ollama). Keep it ``False`` for
    hosted/multi-tenant deployments.
    """
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise UnsafeUrlError(f"URL scheme {parts.scheme!r} is not allowed; use http or https")

    host = parts.hostname
    if not host:
        raise UnsafeUrlError("URL has no host")

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
