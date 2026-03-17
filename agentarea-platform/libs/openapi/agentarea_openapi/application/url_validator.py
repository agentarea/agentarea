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


def validate_url(url: str, *, allow_private: bool = False) -> None:
    """Validate a URL is safe to fetch.

    Args:
        url: The URL to validate.
        allow_private: If True, skip private/internal IP checks.
            Used for self-hosted deployments connecting to local services.

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
        return

    try:
        results = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        raise ValueError(f"Could not resolve hostname '{hostname}': {e}") from e

    for result in results:
        addr_str = result[4][0]
        try:
            addr = ipaddress.ip_address(addr_str)
        except ValueError:
            continue
        for network in _PRIVATE_NETWORKS:
            if addr in network:
                raise ValueError(
                    f"URL resolves to a private/internal IP address ({addr_str}), "
                    "which is not allowed."
                )
