"""Dependency Injection Container for managing application dependencies."""

from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")


class DIContainer:
    """dependency injection container."""

    def __init__(self):
        self._singletons: dict[type[Any], Any] = {}
        self._factories: dict[type[Any], Callable[[], Any]] = {}

    def register_singleton(self, interface: type[T], instance: T) -> None:
        """Register a singleton instance."""
        self._singletons[interface] = instance

    def register_factory(self, interface: type[T], factory: Callable[[], T]) -> None:
        """Register a factory function for creating instances."""
        self._factories[interface] = factory

    def get(self, interface: type[T]) -> T:
        """Get an instance of the requested type."""
        # Check if we have a singleton
        if interface in self._singletons:
            return self._singletons[interface]

        # Check if we have a factory
        if interface in self._factories:
            instance = self._factories[interface]()
            # Store as singleton for future requests
            self._singletons[interface] = instance
            return instance

        raise ValueError(f"No registration found for {interface}")

    def clear(self) -> None:
        """Clear all registrations (useful for testing)."""
        self._singletons.clear()
        self._factories.clear()


# Global container instance
_container = DIContainer()


def get_container() -> DIContainer:
    """Get the global DI container."""
    return _container


def register_singleton(interface: type[T], instance: T) -> None:
    """Convenience function to register a singleton."""
    _container.register_singleton(interface, instance)


def register_factory(interface: type[T], factory: Callable[[], T]) -> None:
    """Convenience function to register a factory."""
    _container.register_factory(interface, factory)


def resolve[T](interface: type[T]) -> T:
    """Convenience function to resolve a dependency."""
    return _container.get(interface)


def get_instance[T](interface: type[T]) -> T:
    """Alias for resolve - convenience function to get a dependency."""
    return _container.get(interface)
