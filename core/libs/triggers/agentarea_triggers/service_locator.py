"""Simple service locator for trigger system dependencies.

This provides a way to register and retrieve services within the trigger system,
particularly useful for activities that need to access services.
"""

from typing import Any

# Global service registry
_services: dict[str, Any] = {}


def register_service(name: str, service: Any) -> None:
    """Register a service in the service locator.

    Args:
        name: The name to register the service under
        service: The service instance to register
    """
    _services[name] = service


def get_service(name: str) -> Any:
    """Get a service from the service locator.

    Args:
        name: The name of the service to retrieve

    Returns:
        The service instance

    Raises:
        KeyError: If the service is not registered
    """
    if name not in _services:
        raise KeyError(f"Service '{name}' not registered")
    return _services[name]


def clear_services() -> None:
    """Clear all registered services. Useful for testing."""
    _services.clear()


def is_service_registered(name: str) -> bool:
    """Check if a service is registered.

    Args:
        name: The name of the service to check

    Returns:
        True if the service is registered, False otherwise
    """
    return name in _services
