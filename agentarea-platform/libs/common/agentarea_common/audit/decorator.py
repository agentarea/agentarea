"""Decorator for automatic audit logging on service methods."""

import functools
import logging
from typing import Any

from .service import AuditService

logger = logging.getLogger(__name__)


def _extract_resource_id(result: Any) -> str | None:
    """Try to get an ID from the method's return value."""
    if result is None:
        return None
    if hasattr(result, "id"):
        return str(result.id)
    if isinstance(result, dict) and "id" in result:
        return str(result["id"])
    return None


_SENSITIVE_FIELD_MARKERS = (
    "api_key",
    "authorization",
    "credential",
    "password",
    "private_key",
    "secret",
    "token",
)

_REDACTED = "***"


def _is_sensitive(field: str) -> bool:
    """Whether a field's *value* must never reach the audit trail.

    Fields ending in ``_id`` are excluded: ``api_key_secret_id`` points at a
    secret rather than holding one, and that reference is exactly the
    provenance an auditor needs.
    """
    lowered = field.lower()
    if lowered.endswith("_id"):
        return False
    return any(marker in lowered for marker in _SENSITIVE_FIELD_MARKERS)


def _redact(value: Any) -> Any:
    """Mask a value while preserving whether it was set at all."""
    return None if value is None else _REDACTED


def _compute_changes(before: dict, after: dict) -> list[dict[str, Any]]:
    """Compute field-level diffs between two dicts.

    Sensitive values are masked: that a credential rotated is auditable, what
    it rotated to is not.
    """
    changes = []
    all_keys = set(before.keys()) | set(after.keys())
    skip = {"created_at", "updated_at"}
    for key in sorted(all_keys - skip):
        old = before.get(key)
        new = after.get(key)
        if str(old) == str(new):
            continue
        if _is_sensitive(key):
            changes.append({"field": key, "before": _redact(old), "after": _redact(new)})
        else:
            changes.append({"field": key, "before": old, "after": new})
    return changes


def audited(
    action: str,
    resource_type: str,
    *,
    resource_id_param: str | None = None,
):
    """Decorator that automatically records audit events for service methods.

    The decorated method's ``self`` must have a ``repository_factory`` attribute
    with ``.session`` and ``.user_context`` (standard service pattern).

    For **create** actions the resource ID is extracted from the return value.
    For **update/delete** actions, pass ``resource_id_param`` to name the
    kwarg or positional arg that holds the ID. The decorator snapshots the
    resource before the method runs to compute a diff.

    Usage::

        class AgentService(BaseCrudService[Agent]):
            @audited("agent.create", resource_type="agent")
            async def create_agent(self, name, ...): ...

            @audited("agent.update", resource_type="agent", resource_id_param="agent_id")
            async def update_agent(self, agent_id, data): ...

            @audited("agent.delete", resource_type="agent", resource_id_param="agent_id")
            async def delete_agent(self, agent_id): ...
    """

    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(self, *args, **kwargs):
            # Build AuditService from the service's repository_factory
            factory = getattr(self, "repository_factory", None)
            if factory is None:
                # Skipping here would leave the action running with no trail
                # and no signal — the wiring bug has to surface instead.
                raise TypeError(
                    f"{type(self).__name__}.{fn.__name__} is @audited('{action}') but has no "
                    "repository_factory; the audit event cannot be recorded."
                )

            audit = AuditService(factory.session, factory.user_context)

            # Resolve resource_id from args/kwargs
            resource_id = None
            if resource_id_param:
                resource_id = kwargs.get(resource_id_param)
                if resource_id is None and args:
                    # Try positional: resource_id_param is typically the first arg
                    import inspect

                    sig = inspect.signature(fn)
                    params = list(sig.parameters.keys())
                    # Skip 'self'
                    if resource_id_param in params:
                        idx = params.index(resource_id_param) - 1  # -1 for self
                        if 0 <= idx < len(args):
                            resource_id = args[idx]

            # Snapshot before-state for updates
            before_state = None
            is_mutation = any(
                verb in action for verb in (".update", ".delete", ".disable", ".enable")
            )
            if is_mutation and resource_id and hasattr(self, "repository"):
                try:
                    existing = await self.repository.get(resource_id)
                    if existing and hasattr(existing, "to_dict"):
                        before_state = existing.to_dict()
                except Exception:
                    logger.warning(
                        "Failed to snapshot resource state for %s (id=%s); "
                        "the audit event will carry no field diff",
                        action,
                        resource_id,
                        exc_info=True,
                    )

            # Execute the actual method
            result = await fn(self, *args, **kwargs)

            # Build audit event
            try:
                final_resource_id = resource_id or _extract_resource_id(result)
                changes = None

                if before_state and result and hasattr(result, "to_dict"):
                    changes = _compute_changes(before_state, result.to_dict())

                await audit.record(
                    action=action,
                    resource_type=resource_type,
                    resource_id=final_resource_id,
                    changes=changes,
                )
            except Exception:
                logger.warning(
                    "Failed to record audit event for %s (resource_type=%s)",
                    action,
                    resource_type,
                    exc_info=True,
                )

            return result

        return wrapper

    return decorator
