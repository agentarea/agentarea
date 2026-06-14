"""SSRF protection: URL validation for outbound HTTP requests."""

import ipaddress
import socket
from urllib.parse import urlparse

_PRIVATE_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]

def validate_url(url: str, *, allow_private: bool = False) -> list[str]:
    """Validate a URL is safe to fetch and return resolved IP addresses.

    Args:
        url: The URL to validate.
        allow_private: If True, skip private/internal IP checks.
            Used for self-hosted deployments connecting to local services.

    Returns:
        List of resolved IP address strings (empty if allow_private).

    Raises:
        ValueError: If the URL is not safe to fetch.
    """
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise ValueError(
            f"URL scheme '{parsed.scheme}' is not allowed. Only http and https are permitted."
        )

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL has no hostname.")

    if allow_private:
        return []

    try:
        results = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        raise ValueError(f"Could not resolve hostname '{hostname}': {e}") from e

    resolved_ips: list[str] = []
    for result in results:
        addr_str = str(result[4][0])
        try:
            addr = ipaddress.ip_address(addr_str)
        except ValueError:
            continue
        resolved_ips.append(addr_str)
        for network in _PRIVATE_NETWORKS:
            if addr in network:
                raise ValueError(
                    f"URL resolves to a private/internal IP address ({addr_str}), "
                    "which is not allowed."
                )

    return resolved_ips


class PinnedTarget:
    """Validated, ready-to-fetch destination split into independent components.

    Holding scheme/host/port separately from path/query lets the HTTP client
    layer construct the request URL without ever concatenating raw user input
    with the destination identifiers — the destination is fully determined by
    `scheme` (allowlisted) and `host` (a `validate_url`-vetted IP), regardless
    of the path.
    """

    __slots__ = ("host", "original_host", "path", "port", "raw_query", "scheme")

    def __init__(
        self,
        scheme: str,
        host: str,
        port: int | None,
        path: str,
        raw_query: bytes,
        original_host: str,
    ) -> None:
        self.scheme = scheme
        self.host = host
        self.port = port
        self.path = path
        self.raw_query = raw_query
        self.original_host = original_host


def build_pinned_target(url: str, resolved_ip: str | None = None) -> PinnedTarget:
    """Build a validated PinnedTarget for an outbound HTTP request.

    Splits the destination identifiers (scheme/host/port) — which determine
    where the request actually goes — from the path/query, which only address
    a resource on the already-vetted destination. Callers construct the
    request URL from this struct via the HTTP client's URL constructor; the
    HTTP sink only ever sees an URL whose destination components come from
    the allowlist + the resolved-IP path through `validate_url`.

    If `resolved_ip` is None (allow_private mode), DNS is resolved inline so
    the request still targets a concrete address.
    """
    parsed = urlparse(url)
    original_host = parsed.hostname or ""
    # Scheme is constrained to two literal constants — no taint reaches the sink.
    scheme = "https" if parsed.scheme == "https" else "http"

    if resolved_ip is None:
        try:
            results = socket.getaddrinfo(original_host, None)
            resolved_ip = str(results[0][4][0]) if results else original_host
        except socket.gaierror:
            resolved_ip = original_host

    return PinnedTarget(
        scheme=scheme,
        host=resolved_ip,
        port=parsed.port,
        path=parsed.path or "/",
        raw_query=parsed.query.encode("ascii", errors="replace") if parsed.query else b"",
        original_host=original_host,
    )


def build_pinned_url(url: str, resolved_ip: str | None = None) -> tuple[str, str, str]:
    """Backwards-compatible wrapper around :func:`build_pinned_target`.

    Returns ``(pinned_url, original_host, path)`` to match the prior API.
    Prefer :func:`build_pinned_target` in new code so the destination
    components stay separated from the user-controlled path.
    """
    target = build_pinned_target(url, resolved_ip)
    ip_host = f"[{target.host}]" if ":" in target.host else target.host
    netloc = f"{ip_host}:{target.port}" if target.port else ip_host
    query = f"?{target.raw_query.decode('ascii')}" if target.raw_query else ""
    pinned = f"{target.scheme}://{netloc}{target.path}{query}"
    return pinned, target.original_host, target.path
