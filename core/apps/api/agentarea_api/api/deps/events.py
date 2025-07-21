"""Event broker dependency for FastAPI endpoints."""

from .services import EventBrokerDep

# Re-export for backward compatibility
__all__ = ["EventBrokerDep"]
