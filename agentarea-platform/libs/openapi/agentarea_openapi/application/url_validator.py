"""SSRF protection: URL validation for outbound HTTP requests."""

import ipaddress
import re
import socket
from urllib.parse import urlparse

from agentarea_common.utils.url_safety import OutboundPolicy

_SPEC_MAX_SIZE = 5 * 1024 * 1024  # 5MB

URL_VARIABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_URL_PLACEHOLDER_RE = re.compile(r"\{([^{}]*)\}")


def url_template_variables(url: str) -> set[str]:
    """Return the ``{name}`` placeholders of a base URL, which may appear only in its path.

    A placeholder is filled from a secret, and a secret must never pick where a
    request goes, so scheme, host, port, query and fragment stay literal.

    Raises:
        ValueError: If a placeholder sits outside the path or is malformed.
    """
    parsed = urlparse(url)
    outside_path = "".join(
        (parsed.scheme, parsed.netloc, parsed.params, parsed.query, parsed.fragment)
    )
    if "{" in outside_path or "}" in outside_path:
        raise ValueError(
            "URL variables are only allowed in the base URL path; "
            "the scheme, host, port and query must be literal."
        )
    names = set(_URL_PLACEHOLDER_RE.findall(parsed.path))
    for name in names:
        if not URL_VARIABLE_NAME_RE.fullmatch(name):
            raise ValueError(f"Invalid URL variable name '{name}'.")
    literal_path = _URL_PLACEHOLDER_RE.sub("", parsed.path)
    if "{" in literal_path or "}" in literal_path:
        raise ValueError("Base URL path has an unmatched '{' or '}'.")
    return names


def check_url_variables(url: str, variable_names: list[str]) -> None:
    """Require every placeholder in ``url`` to have a URL variable, and vice versa."""
    placeholders = url_template_variables(url)
    names = set(variable_names)
    if len(names) != len(variable_names):
        raise ValueError("URL variable names must be unique.")
    missing = sorted(placeholders - names)
    if missing:
        raise ValueError(f"Base URL placeholders have no URL variable: {', '.join(missing)}.")
    unused = sorted(names - placeholders)
    if unused:
        raise ValueError(f"URL variable is not used in the base URL: {', '.join(unused)}.")


def validate_url(url: str, *, policy: OutboundPolicy) -> list[str]:
    """Validate a URL is safe to fetch and return its resolved IP addresses.

    ``policy`` is the deployment's ``OutboundPolicy`` (``OutboundPolicy.from_env()``)
    so this admits exactly what the pinned clients connect to, allowlist included.

    Returns:
        The resolved addresses, empty when the policy allows every private address.

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

    if policy.allow_private:
        return []

    try:
        results = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        raise ValueError(f"Could not resolve hostname '{hostname}': {e}") from e

    resolved_ips: list[str] = []
    for result in results:
        addr_str = str(result[4][0]).split("%")[0]
        try:
            addr = ipaddress.ip_address(addr_str)
        except ValueError:
            continue
        if not policy.permits(hostname, addr):
            raise ValueError(
                f"URL resolves to a private/internal IP address ({addr_str}), which is not allowed."
            )
        if addr_str not in resolved_ips:
            resolved_ips.append(addr_str)

    return resolved_ips
