"""An old index's stub SKILL.md: a pointer to the original, not the skill (ADR-0044).

Before packages existed, the curated and community indexes carried, in place of
each skill, a stub naming where its SKILL.md lives. Installs copied it.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass

import yaml

STUB_MARKER = (
    "Imported system skill metadata. The original SKILL.md should be reviewed before execution."
)
_STUB_FIELDS = ("Source", "Repository", "Path")
_ONE_WORD_FIELDS = ("License", "Distribution")
_STUB_TRAILER = (*_STUB_FIELDS, *_ONE_WORD_FIELDS)
_ONE_WORD = re.compile(r"\S+")
REPO_NAME = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


@dataclass(frozen=True)
class StubSource:
    """Where a stub says the original SKILL.md is."""

    source_url: str
    repo: str
    path: str

    @property
    def folder(self) -> str:
        path = self.path.strip("/")
        return posixpath.dirname(path) if posixpath.basename(path).lower() == "skill.md" else path


def parse_stub(text: str) -> StubSource | None:
    """The original a stub points at; ``None`` unless ``text`` carries the stub's
    exact marker line followed by its Source, Repository and Path lines.
    """
    lines = [line.strip() for line in text.splitlines()]
    if STUB_MARKER not in lines:
        return None
    fields: dict[str, str] = {}
    for line in lines[lines.index(STUB_MARKER) + 1 :]:
        key, sep, value = line.partition(": ")
        if sep and key in _STUB_FIELDS and key not in fields:
            fields[key] = value.strip()
    if not all(fields.get(key) for key in _STUB_FIELDS):
        return None
    return StubSource(fields["Source"], fields["Repository"], fields["Path"])


def bare_stub(text: str, *, name: str, description: str | None) -> StubSource | None:
    """What :func:`parse_stub` finds, when ``text`` is exactly the stub an index wrote
    for the skill ``name`` with ``description``, else ``None``.

    That is a frontmatter of only that name and description, the description as
    the one paragraph before the marker, then Source, Repository and Path once
    each and at most a one-word License and Distribution. Anything else in it
    is someone's edit.
    """
    stub = parse_stub(text)
    if stub is None or description is None:
        return None
    lines = [line.strip() for line in text.splitlines()]
    if not lines or lines[0] != "---" or "---" not in lines[1:]:
        return None
    close = lines.index("---", 1)
    try:
        meta = yaml.safe_load("\n".join(text.splitlines()[1:close]))
    except yaml.YAMLError:
        return None
    if not isinstance(meta, dict) or set(meta) != {"name", "description"}:
        return None
    if meta["name"] != name or _words(meta["description"]) != _words(description):
        return None
    marker = lines.index(STUB_MARKER)
    if close > marker or _words(" ".join(lines[close + 1 : marker])) != _words(description):
        return None
    seen: set[str] = set()
    for line in filter(None, lines[marker + 1 :]):
        key, sep, value = line.partition(": ")
        if not sep or key not in _STUB_TRAILER or key in seen:
            return None
        if key in _ONE_WORD_FIELDS and not _ONE_WORD.fullmatch(value):
            return None
        seen.add(key)
    if not REPO_NAME.fullmatch(stub.repo) or not re.fullmatch(
        rf"https://github\.com/{re.escape(stub.repo)}(/\S*)?", stub.source_url
    ):
        return None
    if stub.path.startswith("/") or ".." in stub.path.split("/") or " " in stub.path:
        return None
    return stub


def _words(value: object) -> str | None:
    return " ".join(value.split()) if isinstance(value, str) else None
