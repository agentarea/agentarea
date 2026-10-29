"""AgentArea Common Library."""

from importlib.metadata import version

from . import (
    auth,
    base,
    config,
    di,
    events,
    exceptions,
    infrastructure,
    logging,
    money,
    testing,
    utils,
    workflow,
)

__version__ = version("agentarea-common")

__all__ = [
    "auth",
    "base",
    "config",
    "di",
    "events",
    "exceptions",
    "infrastructure",
    "logging",
    "money",
    "testing",
    "utils",
    "workflow",
]
