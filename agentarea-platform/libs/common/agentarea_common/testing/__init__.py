"""Testing utilities for AgentArea.

This module provides shared test implementations and mock objects
to avoid duplication across test files.
"""

from .graph import (
    AllowAllPermissions,
    RecordingGraph,
    allow_all_permissions,
    install_graph_ownership_stub,
)
from .mocks import TestEventBroker, TestSecretManager

__all__ = [
    "AllowAllPermissions",
    "RecordingGraph",
    "TestEventBroker",
    "TestSecretManager",
    "allow_all_permissions",
    "install_graph_ownership_stub",
]
