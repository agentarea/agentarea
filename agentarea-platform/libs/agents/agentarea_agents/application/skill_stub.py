"""An old index's stub SKILL.md: a pointer to the original, not the skill (ADR-0044).

Before packages existed, the curated and community indexes carried, in place of
each skill, a stub naming where its SKILL.md lives. Installs copied it.
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass

STUB_MARKER = (
    "Imported system skill metadata. The original SKILL.md should be reviewed before execution."
)
_STUB_FIELDS = ("Source", "Repository", "Path")
# What an index wrote after the marker; any other line there is someone's edit.
_STUB_TRAILER = (*_STUB_FIELDS, "License", "Distribution")


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


def bare_stub(text: str) -> StubSource | None:
    """What :func:`parse_stub` finds, when nothing but the stub's own lines follow its marker."""
    stub = parse_stub(text)
    if stub is None:
        return None
    lines = [line.strip() for line in text.splitlines()]
    trailer = lines[lines.index(STUB_MARKER) + 1 :]
    if any(line and line.partition(": ")[0] not in _STUB_TRAILER for line in trailer):
        return None
    return stub
