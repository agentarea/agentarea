"""Content hash of an agent's declared configuration.

The hash identifies *what the agent was configured to be* at a point in time, so
a run can be compared against the agent's current definition ("this task did not
run the config you are looking at"). It is a change detector, not a snapshot:
without the preimage it tells you that two configs differ, never how.

Scope is deliberately narrow — it covers the agent's own declaration, not the
resolved environment. A tool entry references an MCP instance by id; that
instance's own settings can change without moving this hash.
"""

import hashlib
import json
from typing import Any

# Bump when the hashed field set changes, so hashes computed under different
# rules are never compared as if they meant the same thing.
CONFIG_HASH_VERSION = "v1"

# Only fields the runtime actually acts on. Renaming an agent must not look like
# a behaviour change.
_HASHED_FIELDS = (
    "instruction",
    "model_id",
    "tools",
    "events_config",
    "planning",
    "agent_type",
)


def _canonical(value: Any) -> Any:
    """Return ``value`` in a form whose JSON encoding is order-independent."""
    if isinstance(value, dict):
        return {k: _canonical(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        # Tool order carries no meaning, so a reordered list is the same config.
        return sorted((_canonical(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True))
    return value


def compute_agent_config_hash(
    config: dict[str, Any],
    skill_ids: list[str] | None = None,
) -> str:
    """Hash the execution-relevant parts of an agent config.

    Args:
        config: Agent fields; keys outside the hashed set are ignored, and
            missing keys hash the same as keys explicitly set to ``None``.
        skill_ids: Attached skill ids. Skills change behaviour and are stored
            through a separate relation, so they must be passed in explicitly
            rather than read off ``config``.

    Returns:
        ``"<version>:<sha256 hex>"``.
    """
    payload = {field: _canonical(config.get(field)) for field in _HASHED_FIELDS}
    payload["skill_ids"] = sorted(str(s) for s in (skill_ids or []))

    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return f"{CONFIG_HASH_VERSION}:{hashlib.sha256(encoded).hexdigest()}"
