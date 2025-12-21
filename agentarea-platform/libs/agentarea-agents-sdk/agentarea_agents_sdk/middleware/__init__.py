"""Middleware components for stateful agents.

Inspired by LangChain Deep Agents architecture.
"""

from .base import Middleware, MiddlewareStack
from .state import StateBackend, InMemoryState
from .todolist import TodoListMiddleware
from .filesystem import FilesystemMiddleware
from .summarization import SummarizationMiddleware
from .subagents import SubAgentMiddleware, TaskTool

__all__ = [
    "Middleware",
    "MiddlewareStack",
    "StateBackend",
    "InMemoryState",
    "TodoListMiddleware",
    "FilesystemMiddleware",
    "SummarizationMiddleware",
    "SubAgentMiddleware",
    "TaskTool",
]
