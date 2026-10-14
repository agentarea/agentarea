"""Which certificate authorities the platform trusts when it dials out.

Every request the platform sends to a host outside the deployment checks TLS
against one trust store: the system's CAs and certifi's bundle, plus the PEM
file ``AGENTAREA_HTTP_EXTRA_CA_CERTS`` names. The file adds to the public roots
and never replaces them. It is for chains those roots leave out, such as hosts
certified by the Russian Trusted Root CA or a corporate CA.
"""

import functools
import ssl

import certifi

__all__ = ["OutboundTrustError", "install_outbound_trust", "outbound_ssl_context"]

_ENV_NAME = "AGENTAREA_HTTP_EXTRA_CA_CERTS"


class OutboundTrustError(RuntimeError):
    """The configured extra CA bundle cannot be loaded."""


@functools.cache
def outbound_ssl_context() -> ssl.SSLContext:
    """The TLS context for outbound requests, built once per process.

    Pass it as ``verify=`` to an httpx or httpx2 client or transport.
    """
    from agentarea_common.config import get_settings

    context = ssl.create_default_context(cafile=certifi.where())
    context.load_default_certs(ssl.Purpose.SERVER_AUTH)
    extra = get_settings().http.EXTRA_CA_CERTS.strip()
    if extra:
        try:
            context.load_verify_locations(cafile=extra)
        except (OSError, ssl.SSLError) as exc:
            raise OutboundTrustError(
                f"{_ENV_NAME}={extra} names no readable PEM file of CA certificates: {exc}"
            ) from exc
    return context


def install_outbound_trust() -> None:
    """Load the outbound trust store at startup, so a bad bundle stops the process."""
    outbound_ssl_context()
