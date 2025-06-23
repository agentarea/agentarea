"""Testing utilities for AgentArea.

This module provides shared test implementations and mock objects
to avoid duplication across test files.
"""

from .mocks import TestEventBroker, TestSecretManager

__all__ = ["TestEventBroker", "TestSecretManager"]
