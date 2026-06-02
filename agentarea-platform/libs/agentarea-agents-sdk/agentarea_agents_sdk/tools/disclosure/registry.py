"""Factory + registry for ToolDisclosurePolicy.

Maps a config string or dict (e.g. `load_mode: "searchable"` from YAML) to a
concrete policy instance. New policies register themselves once at import.
"""

from __future__ import annotations

from collections.abc import Callable

from .protocol import ToolDisclosurePolicy

_REGISTRY: dict[str, Callable[[], ToolDisclosurePolicy]] = {}


def register_policy(name: str, factory: Callable[[], ToolDisclosurePolicy]) -> None:
    """Register a policy factory under a name. Idempotent — last write wins."""
    _REGISTRY[name] = factory


def list_policies() -> list[str]:
    """Names of all registered policies."""
    return sorted(_REGISTRY.keys())


def policy_from_config(config: str | dict | None) -> ToolDisclosurePolicy:
    """Resolve a config value into a policy instance.

    Accepts:
        None         -> ExplicitPolicy (registered as "explicit")
        "<name>"     -> registered factory by name
        {"name": x}  -> registered factory by x
    """
    if config is None:
        name = "explicit"
    elif isinstance(config, str):
        name = config
    elif isinstance(config, dict):
        raw = config.get("name", "")
        if not isinstance(raw, str) or not raw:
            raise ValueError(
                f"disclosure policy config dict must have non-empty 'name': {config!r}"
            )
        name = raw
    else:
        raise ValueError(
            f"disclosure policy config must be None, str, or dict; got {type(config).__name__}"
        )

    factory = _REGISTRY.get(name)
    if factory is None:
        raise ValueError(
            f"Unknown disclosure policy: {name!r}. Available: {sorted(_REGISTRY.keys())}"
        )
    return factory()
