"""Template substitutions: how a catalog entry reads an event, and fills a request (ADR-0040 §2).

Not a language. A template is literal text with placeholders:

- ``{body:a.b.0.c}``: a dotted path into the body (a number indexes a list);
  ``{body:a.b|c.d}``: the first of several paths that is present;
- ``{header:name}``: a request header, case-insensitive;
- ``{first_key:a|b|c}``: the name of the first of these keys the body has;
- ``{name}`` / ``{scope.name}`` / ``{scope:name}``: a value the caller supplies
  (``credentials.bot_token``, ``target:chat_id``, ``message``, ``webhook_url``).

A template without placeholders is a constant. A placeholder with no value makes
the whole field absent: a key that cannot be read is no key, not a wrong one. A
field may list several templates; the first that renders is its value (GitHub's
kind is ``{header:x-github-event}.{body:action}``, or the event alone when the
body has no action). Nothing is computed, converted or branched on.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

_PLACEHOLDER = re.compile(r"\{([^{}]+)\}")


class TemplateError(ValueError):
    """A template is malformed: an unknown placeholder kind or an empty path."""


@dataclass(frozen=True)
class TemplateContext:
    """What a template may read: the body and headers of an event, and named values."""

    body: Any = None
    headers: Mapping[str, str] = field(default_factory=dict)
    values: Mapping[str, Any] = field(default_factory=dict)

    def header(self, name: str) -> str | None:
        wanted = name.lower()
        for key, value in self.headers.items():
            if str(key).lower() == wanted:
                return value
        return None


def path_value(data: Any, path: str) -> Any:
    """The value at a dotted ``path`` in ``data``, or None when any step is missing."""
    if not path:
        raise TemplateError("a path placeholder needs a path")
    current = data
    for step in path.split("."):
        if isinstance(current, Mapping):
            if step not in current:
                return None
            current = current[step]
        elif isinstance(current, list) and step.isdigit():
            index = int(step)
            if index >= len(current):
                return None
            current = current[index]
        else:
            return None
    return current


def _first_path(data: Any, paths: str) -> Any:
    for path in paths.split("|"):
        value = path_value(data, path.strip())
        if value is not None and value != "":
            return value
    return None


def placeholder_value(expression: str, context: TemplateContext) -> Any:
    """The value of one placeholder's expression, or None when it has none."""
    kind, sep, argument = expression.partition(":")
    if sep:
        kind = kind.strip()
        if kind == "body":
            return _first_path(context.body, argument)
        if kind == "header":
            return context.header(argument.strip())
        if kind == "first_key":
            if not isinstance(context.body, Mapping):
                return None
            return next(
                (key for key in (k.strip() for k in argument.split("|")) if key in context.body),
                None,
            )
        if kind in context.values:
            scope = context.values[kind]
            return path_value(scope, argument.strip()) if isinstance(scope, Mapping) else None
        raise TemplateError(f"unknown placeholder kind {kind!r} in {{{expression}}}")
    name = expression.strip()
    if name in context.values:
        return context.values[name]
    scope, dot, rest = name.partition(".")
    if dot and scope in context.values and isinstance(context.values[scope], Mapping):
        return path_value(context.values[scope], rest)
    return None


def render(template: str | None, context: TemplateContext) -> str | None:
    """The template filled in, or None when it is None or any placeholder has no value."""
    if template is None:
        return None
    parts: list[str] = []
    position = 0
    for match in _PLACEHOLDER.finditer(template):
        parts.append(template[position : match.start()])
        value = placeholder_value(match.group(1), context)
        if value is None or value == "":
            return None
        parts.append(value if isinstance(value, str) else _scalar(value))
        position = match.end()
    parts.append(template[position:])
    return "".join(parts)


def render_first(templates: str | list[str] | None, context: TemplateContext) -> str | None:
    """The first of ``templates`` that renders, or None when none does."""
    if templates is None or isinstance(templates, str):
        return render(templates, context)
    for template in templates:
        if (value := render(template, context)) is not None:
            return value
    return None


def render_value(template: Any, context: TemplateContext) -> Any:
    """A JSON value with every string leaf rendered.

    A leaf that is exactly one placeholder keeps the value's own type (a chat id
    stays a number); a leaf that cannot be rendered is left out of its object,
    and an object left with nothing is left out of its parent.
    """
    if isinstance(template, str):
        whole = _PLACEHOLDER.fullmatch(template)
        if whole is not None:
            return placeholder_value(whole.group(1), context)
        return render(template, context)
    if isinstance(template, Mapping):
        rendered = {key: render_value(value, context) for key, value in template.items()}
        kept = {key: value for key, value in rendered.items() if value is not None}
        # An object every leaf of which was left out is left out with them.
        return kept if kept or not template else None
    if isinstance(template, list):
        return [render_value(item, context) for item in template]
    return template


def _scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    raise TemplateError(f"a placeholder inside text must be a scalar, got {type(value).__name__}")
