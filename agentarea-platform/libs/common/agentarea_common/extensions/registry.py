"""Plugin extension registry for OSS/Enterprise feature separation."""

from collections.abc import Callable
from typing import Any


class ExtensionRegistry:
    """Registry mapping extension point names to factory callables.

    Factory callables create instances of the corresponding interface.
    This allows enterprise implementations to manage their own dependencies
    (e.g., KetoPermissionService needs a keto_client).
    """

    _factories: dict[str, Callable[[], Any]] = {}

    @classmethod
    def register(cls, interface: str, factory: Callable[[], Any]) -> None:
        """Register a factory for an extension point."""
        cls._factories[interface] = factory

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
