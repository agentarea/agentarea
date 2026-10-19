r"""Whether a JSON value survives a round trip through Postgres text.

Postgres text cannot hold NUL, and jsonb rejects ``\u0000`` and unpaired
surrogates. A plain ``json`` column accepts both, then fails every ``->>`` that
has to render them, so they must be refused where they enter.
"""

from __future__ import annotations

from typing import Any


def _text_problem(text: str) -> str | None:
    if "\x00" in text:
        return "contains a NUL character"
    for char in text:
        if "\ud800" <= char <= "\udfff":
            return "contains an unpaired UTF-16 surrogate"
    return None


def pg_text_problem(value: Any, path: str = "$") -> str | None:
    """Describe the first string Postgres cannot store as text, or ``None``."""
    if isinstance(value, str):
        problem = _text_problem(value)
        return f"{path} {problem}" if problem else None
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str) and (problem := _text_problem(key)):
                return f"a key in {path} {problem}"
            if found := pg_text_problem(item, f"{path}.{key}"):
                return found
    if isinstance(value, list):
        for index, item in enumerate(value):
            if found := pg_text_problem(item, f"{path}[{index}]"):
                return found
    return None


def require_pg_text(value: Any) -> Any:
    """Pydantic ``AfterValidator``: refuse JSON Postgres cannot store as text."""
    if problem := pg_text_problem(value):
        raise ValueError(problem)
    return value


def _storable_text(text: str) -> str:
    if "\x00" not in text and not any("\ud800" <= char <= "\udfff" for char in text):
        return text
    return "".join("�" if char == "\x00" or "\ud800" <= char <= "\udfff" else char for char in text)


def pg_storable(value: Any) -> Any:
    """``value`` with every NUL and unpaired surrogate replaced by U+FFFD, keys included.

    For content the platform did not author (a tool's output, a model's reply):
    refusing it would lose the whole row, so the characters Postgres cannot
    store are replaced where the content enters the store.
    """
    if isinstance(value, str):
        return _storable_text(value)
    if isinstance(value, dict):
        return {
            (_storable_text(key) if isinstance(key, str) else key): pg_storable(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [pg_storable(item) for item in value]
    return value
