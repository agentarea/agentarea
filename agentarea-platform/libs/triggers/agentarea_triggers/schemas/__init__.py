"""Trigger schemas — Pydantic DTOs shared by REST API and MCP toolset.

Field descriptions are LLM-facing (they end up in the MCP tool schema) but
are equally suitable for OpenAPI clients reading the REST docs.
"""

from .dto import TriggerCreate, TriggerUpdate

__all__ = ["TriggerCreate", "TriggerUpdate"]
