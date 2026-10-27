"""Failure counters: attempts that leave no row, counted in memory and sent hourly.

Labels are short enum-like values, never a name, id, URL path or free text; a value
that is not one is sent as ``other``. With analytics off there is no sender and
counting does nothing.
"""

import logging
import re

from .runtime import current_sender

logger = logging.getLogger(__name__)

_LABEL_VALUE = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}")

# The entitlement codes billing refuses a model call with (agentarea_execution
# workflows/agent/errors.py): a balance that ran out, and billing that could not
# answer, which refuses nothing. A gate denial without a code is policy's.
_CREDIT_CODES = frozenset({"no_credits", "credit_limit_reached"})
_BILLING_OUTAGE_CODES = frozenset({"billing_unavailable", "billing_error", "account_unresolved"})


def count(name: str, **labels: str) -> None:
    """Add one to ``name`` under ``labels``. Never raises."""
    sender = current_sender()
    if sender is None:
        return
    try:
        sender.count(name, {key: enum_label(value) for key, value in labels.items()})
    except Exception:
        logger.warning("Could not count %s", name, exc_info=True)


def count_run_refused(entitlement_code: str | None) -> None:
    """A run the gate or billing refused: for credits, by policy, else ``other``."""
    if entitlement_code in _BILLING_OUTAGE_CODES:
        return
    if entitlement_code is None:
        reason = "policy_denied"
    elif entitlement_code in _CREDIT_CODES:
        reason = "no_credits"
    else:
        reason = "other"
    count("run_refused", reason=reason)


def enum_label(value: str) -> str:
    """``value`` if enum-like; ``failed:<code>`` keeps its prefix when only the code is not."""
    parts = str(value).lower().split(":", 1)
    return ":".join(part if _LABEL_VALUE.fullmatch(part) else "other" for part in parts)
