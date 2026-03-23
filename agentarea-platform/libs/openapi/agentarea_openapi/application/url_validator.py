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

_SPEC_MAX_SIZE = 5 * 1024 * 1024  # 5MB


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
        addr_str = result[4][0]
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


def build_pinned_url(url: str, resolved_ip: str) -> tuple[str, str]:
    """Replace hostname with a validated IP to prevent DNS rebinding.

    Returns (pinned_url, original_hostname) so callers can set the Host header.
    """
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    # Wrap IPv6 in brackets
    ip_host = f"[{resolved_ip}]" if ":" in resolved_ip else resolved_ip
    # Preserve port if present
    if parsed.port:
        netloc = f"{ip_host}:{parsed.port}"
    else:
        netloc = ip_host
    pinned = parsed._replace(netloc=netloc).geturl()
    return pinned, hostname
