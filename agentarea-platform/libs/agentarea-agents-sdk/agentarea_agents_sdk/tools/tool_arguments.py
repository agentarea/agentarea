"""Checking a model's arguments against the tool method they call, before the call.

The schema a toolset advertises is derived from each method's signature
(``Toolset._get_parameter_schema``). The same signature is the contract here:
a required parameter must be present, and a parameter advertised as
``integer``, ``number``, ``boolean``, ``string``, ``array`` or ``object`` must
hold that type. A numeric or boolean string where the schema says integer,
number or boolean is converted when nothing is lost; anything else is refused
with the field named as the model sees it. Parameters whose type the schema
cannot state exactly (models, unions, ``Any``) are passed through unchecked.
"""

from __future__ import annotations

import inspect
import math
import re
import types
from collections.abc import Callable
from typing import Any, Union, get_args, get_origin, get_type_hints

from .base_tool import ToolError

_INTEGER = re.compile(r"[+-]?\d+")
_BOOLEANS = {"true": True, "false": False}
_ARTICLE = {"integer": "an integer", "object": "an object", "array": "an array"}


class ToolArgumentError(ToolError):
    """The model's arguments do not fit the tool's schema; the message names the field."""


def _advertised_type(hint: Any) -> tuple[str | None, bool]:
    """The JSON type ``hint`` is advertised as, when exact, and whether it admits null."""
    origin = get_origin(hint)
    nullable = False
    if origin in (types.UnionType, Union):
        members = [arg for arg in get_args(hint) if arg is not type(None)]
        nullable = len(members) < len(get_args(hint))
        if len(members) != 1:
            return None, nullable
        hint = members[0]
        origin = get_origin(hint)
    if hint is bool:
        return "boolean", nullable
    if hint is int:
        return "integer", nullable
    if hint is float:
        return "number", nullable
    if hint is str:
        return "string", nullable
    if hint is list or origin is list:
        return "array", nullable
    if hint is dict or origin is dict:
        return "object", nullable
    return None, nullable


def _describe(json_type: str) -> str:
    return _ARTICLE.get(json_type, f"a {json_type}")


def _coerce(field: str, json_type: str, value: Any) -> Any:
    if json_type == "integer":
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str) and _INTEGER.fullmatch(value.strip()):
            return int(value.strip())
    elif json_type == "number":
        if isinstance(value, int | float) and not isinstance(value, bool):
            return value
        if isinstance(value, str):
            try:
                number = float(value.strip())
            except ValueError:
                number = math.nan
            if math.isfinite(number):
                return number
    elif json_type == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in _BOOLEANS:
            return _BOOLEANS[value.strip().lower()]
    elif json_type == "string":
        if isinstance(value, str):
            return value
    elif json_type == "array":
        if isinstance(value, list):
            return value
    elif json_type == "object":
        if isinstance(value, dict):
            return value
    raise ToolArgumentError(f"'{field}' must be {_describe(json_type)}, got {value!r}")


def check_arguments(
    method: Callable[..., Any], kwargs: dict[str, Any], *, field_prefix: str = ""
) -> dict[str, Any]:
    """``kwargs`` checked and converted for ``method``; raises ``ToolArgumentError``.

    ``field_prefix`` is the ``{method}_`` a multi-method toolset puts on each
    parameter in its schema, so errors name the field the model actually sent.
    """
    signature = inspect.signature(method)
    hints = get_type_hints(method)
    parameters = {
        name: param
        for name, param in signature.parameters.items()
        if name != "self"
        and param.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
    }
    takes_any = any(
        param.kind is inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values()
    )
    unknown = sorted(set(kwargs) - set(parameters))
    if unknown and not takes_any:
        expected = ", ".join(f"'{field_prefix}{name}'" for name in parameters) or "none"
        raise ToolArgumentError(
            f"unknown argument '{field_prefix}{unknown[0]}'; expected arguments: {expected}"
        )

    missing = [
        f"'{field_prefix}{name}'"
        for name, param in parameters.items()
        if param.default is inspect.Parameter.empty and kwargs.get(name) is None
    ]
    if missing:
        raise ToolArgumentError(f"missing required argument {', '.join(missing)}")

    checked = dict(kwargs)
    for name, param in parameters.items():
        if name not in kwargs:
            continue
        json_type, nullable = _advertised_type(hints.get(name, Any))
        value = kwargs[name]
        if value is None and (nullable or param.default is None):
            continue
        if json_type is not None:
            checked[name] = _coerce(f"{field_prefix}{name}", json_type, value)
    return checked
