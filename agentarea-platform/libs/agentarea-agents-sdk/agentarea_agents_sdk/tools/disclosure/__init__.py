"""Tool disclosure policies — Strategy + Factory for managing per-call context."""

from .policies import LOAD_TOOLS_NAME, ExplicitPolicy, NamedLookupPolicy
from .protocol import (
    DisclosureContext,
    Partition,
    RevealRequest,
    RevealResult,
    SearchableEntry,
    ToolCandidate,
    ToolDisclosurePolicy,
)
from .registry import list_policies, policy_from_config, register_policy

# Built-in policy registrations. `searchable` is the YAML shorthand alias users
# put into ToolSettingsYAML.load_mode; named_lookup is the canonical name.
register_policy("explicit", ExplicitPolicy)
register_policy("named_lookup", NamedLookupPolicy)
register_policy("searchable", NamedLookupPolicy)

__all__ = [
    "DisclosureContext",
    "ExplicitPolicy",
    "LOAD_TOOLS_NAME",
    "NamedLookupPolicy",
    "Partition",
    "RevealRequest",
    "RevealResult",
    "SearchableEntry",
    "ToolCandidate",
    "ToolDisclosurePolicy",
    "list_policies",
    "policy_from_config",
    "register_policy",
]
