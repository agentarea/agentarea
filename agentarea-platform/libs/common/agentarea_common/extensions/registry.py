"""Plugin extension registry for OSS/Enterprise feature separation."""

from collections.abc import Callable
from typing import Any, ClassVar


class ExtensionRegistry:
    """Registry mapping extension point names to factory callables.

    Factory callables create instances of the corresponding interface.
    This allows enterprise implementations to manage their own dependencies
    (e.g., KetoPermissionService needs a keto_client).
    """

    _factories: ClassVar[dict[str, Callable[[], Any]]] = {}
    # Extension points whose entry point was installed but failed to load, with the
    # reason. Discovery skips these so one broken plugin does not stop the rest,
    # which is right for most points — but an extension point that must not
    # silently degrade (customer_pricing) needs to tell "not installed" from
    # "installed and broken", and only this records the difference.
    _failures: ClassVar[dict[str, str]] = {}

    @classmethod
    def register(cls, interface: str, factory: Callable[[], Any]) -> None:
        """Register a factory for an extension point."""
        cls._factories[interface] = factory
        cls._failures.pop(interface, None)

    @classmethod
    def record_failure(cls, interface: str, reason: str) -> None:
        """Record that an installed extension for this point failed to load."""
        cls._failures[interface] = reason

    @classmethod
    def get_failure(cls, interface: str) -> str | None:
        """Why an installed extension for this point failed to load, or None."""
        return cls._failures.get(interface)

    @classmethod
    def get_factory(cls, interface: str) -> Callable[[], Any] | None:
        """Get the factory for an extension point, or None."""
        return cls._factories.get(interface)

    @classmethod
    def has(cls, interface: str) -> bool:
        """Check if an extension point has a registered factory."""
        return interface in cls._factories

    @classmethod
    def clear(cls) -> None:
        """Clear all registrations. For testing only."""
        cls._factories = {}
        cls._failures = {}
