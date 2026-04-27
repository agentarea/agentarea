"""Canonical tool format shared by MCP, OpenAI function-calling, and internal callers.

ToolDefinition mirrors the MCP `tools/list` shape (`name`, `description`, `inputSchema`)
and the Pydantic AI `ToolDefinition` shape — same three fields, generated from a
Pydantic JSON Schema. This is the single source of truth: REST routers, MCP
toolsets, and internal services all consume Pydantic models, and this module
turns one of those models (or a callable signature) into a tool advertisement.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, get_type_hints

from pydantic import BaseModel, ConfigDict, Field, create_model


class ToolDefinition(BaseModel):
    """LLM-facing tool advertisement (MCP / OpenAI function-calling shape)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    parameters_json_schema: dict[str, Any] = Field(default_factory=dict)

    def to_mcp(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.parameters_json_schema,
        }

    def to_openai(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_json_schema,
            },
        }


class ToolsetMetadata(BaseModel):
    """Class-level metadata for a Toolset.

    Replaces the per-toolset block in ``code_tools.yaml``: namespace
    (publisher/name), human display label, category, admin/visibility flags.
    Stamped onto the class via ``@toolset(...)``.
    """

    model_config = ConfigDict(extra="forbid")

    namespace: str
    display_name: str = ""
    description: str = ""
    category: str = ""
    admin: bool = False
    enabled_by_default: bool = False
    requires_user_confirmation: bool = False


def toolset(
    *,
    namespace: str,
    display_name: str = "",
    description: str = "",
    category: str = "",
    admin: bool = False,
    enabled_by_default: bool = False,
    requires_user_confirmation: bool = False,
) -> Callable[[type], type]:
    """Stamp ``ToolsetMetadata`` on a Toolset subclass."""

    meta = ToolsetMetadata(
        namespace=namespace,
        display_name=display_name,
        description=description,
        category=category,
        admin=admin,
        enabled_by_default=enabled_by_default,
        requires_user_confirmation=requires_user_confirmation,
    )

    def decorator(cls: type) -> type:
        cls.__toolset_meta__ = meta
        return cls

    return decorator


def _is_basemodel(annotation: Any) -> bool:
    return isinstance(annotation, type) and issubclass(annotation, BaseModel)


def build_method_schema(method: Callable) -> dict[str, Any]:
    """Build a JSON Schema for a method's parameters.

    Conventions (matching Pydantic AI):
    - If the method has a single non-self parameter typed as a Pydantic
      ``BaseModel``, the tool schema *is* that model's JSON Schema (flattened).
    - Otherwise, parameters are wrapped into a synthetic Pydantic model so
      that primitives, ``BaseModel`` fields, ``list``/``dict``/``Literal`` and
      ``Optional`` types all render correctly via ``model_json_schema()``.
    """

    sig = inspect.signature(method)
    try:
        hints = get_type_hints(method)
    except Exception:
        hints = {}

    params = [(name, p) for name, p in sig.parameters.items() if name != "self"]

    if len(params) == 1:
        only_name, only_param = params[0]
        annotation = hints.get(only_name, only_param.annotation)
        if _is_basemodel(annotation):
            return annotation.model_json_schema()

    fields: dict[str, tuple[Any, Any]] = {}
    for name, param in params:
        annotation = hints.get(name, param.annotation)
        if annotation is inspect.Parameter.empty:
            annotation = str
        default = ... if param.default is inspect.Parameter.empty else param.default
        fields[name] = (annotation, Field(default=default))

    if not fields:
        return {"type": "object", "properties": {}}

    Model = create_model(f"{method.__name__}_args", **fields)  # type: ignore[call-overload]
    return Model.model_json_schema()


def build_tool_definition(
    *,
    tool_name: str,
    method: Callable,
    description: str | None = None,
) -> ToolDefinition:
    desc = description
    if not desc:
        desc = getattr(method, "_tool_description", None) or (
            method.__doc__.strip().split("\n")[0] if method.__doc__ else method.__name__
        )
    return ToolDefinition(
        name=tool_name,
        description=desc,
        parameters_json_schema=build_method_schema(method),
    )
