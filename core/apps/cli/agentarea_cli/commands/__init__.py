"""CLI commands package."""

from agentarea_cli.commands.a2a import a2a
from agentarea_cli.commands.agent import agent
from agentarea_cli.commands.auth import auth
from agentarea_cli.commands.chat import chat
from agentarea_cli.commands.llm import llm
from agentarea_cli.commands.system import system

__all__ = ["a2a", "agent", "auth", "chat", "llm", "system"]
