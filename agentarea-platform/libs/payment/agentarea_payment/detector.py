"""Detect payment protocol from HTTP 402 responses."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class PaymentProtocolDetector:
    """Inspects HTTP 402 response headers to determine which payment protocol is required."""

    @staticmethod
    def detect(status_code: int, headers: dict[str, str]) -> str | None:
        """Detect the payment protocol from a 402 response.

        Returns "x402", "mpp", or None if unknown.
        """
        if status_code != 402:
            return None

        # Normalize header keys to lowercase for case-insensitive matching
        lower_headers = {k.lower(): v for k, v in headers.items()}

        # x402: look for PAYMENT-REQUIRED header
        if "payment-required" in lower_headers:
            logger.debug("Detected x402 protocol from PAYMENT-REQUIRED header")
            return "x402"

        # MPP: current spec uses WWW-Authenticate: Payment ...
        www_auth = lower_headers.get("www-authenticate", "")
        www_auth_lower = www_auth.lower()
        if "mpp" in www_auth_lower or www_auth_lower.startswith("payment"):
            logger.debug("Detected MPP protocol from WWW-Authenticate header")
            return "mpp"

        logger.debug("Unknown 402 protocol - no recognized payment headers")
        return None
