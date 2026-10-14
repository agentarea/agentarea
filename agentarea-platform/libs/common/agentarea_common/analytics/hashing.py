"""Ids that leave the installation, made meaningless outside it."""

import hashlib
import hmac


def pseudonymize(install_id: str, value: str) -> str:
    """``value`` keyed by the installation: countable inside it, unlinkable outside it."""
    return hmac.new(install_id.encode(), value.encode(), hashlib.sha256).hexdigest()[:16]
