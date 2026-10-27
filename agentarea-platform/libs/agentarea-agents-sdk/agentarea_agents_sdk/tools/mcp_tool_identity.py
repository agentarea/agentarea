"""Which server an MCP tool belongs to, and the name the model calls it by.

Raw MCP tool names are only unique within one server: two attached servers can
both advertise ``search``. The model-facing name therefore carries the server
(``mcp__<server>__<tool>``), while the identity behind it keeps what routing and
policy need — the instance id and the raw name the server advertised.

The server segment is ASCII. A name already written in ASCII keeps the segment
it always had (so existing tool names and rules naming them do not change); a
name with other letters is transliterated (Cyrillic) or folded (accented Latin)
and collapsed to ``[a-z0-9_]``, so "Constractio — инструменты сметчика" becomes
``constractio_instrumenty_smetchika`` instead of a run of underscores.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass

MAX_TOOL_NAME_LENGTH = 64
_PREFIX = "mcp"
_DELIMITER = "__"
_INVALID = re.compile(r"[^a-zA-Z0-9_-]")
_NOT_SLUG = re.compile(r"[^a-z0-9]+")

# Lowercase Cyrillic (Russian, Ukrainian, Belarusian) to Latin, one-way, for names
# only: readable and stable, not a reversible standard.
_CYRILLIC_LETTERS = "абвгдеёжзийклмнопрстуфхцчшщъыьэюяіїєґў"
# One Latin reading per letter above, in order; "-" means the letter is dropped.
_CYRILLIC_LATIN = (
    "a b v g d e e zh z i y k l m n o p r s t u f h ts ch sh sch - y - e yu ya i yi ye g u"
).split()
_CYRILLIC = str.maketrans(
    {
        letter: "" if latin == "-" else latin
        for letter, latin in zip(_CYRILLIC_LETTERS, _CYRILLIC_LATIN, strict=True)
    }
)


def _sanitize(value: str) -> str:
    return _INVALID.sub("_", value)


def ascii_slug(name: str) -> str:
    """``name`` as ``[a-z0-9_]``: Cyrillic transliterated, accents dropped.

    Letters with no Latin reading (CJK, say) are dropped; the result may be empty.
    """
    latin = name.lower().translate(_CYRILLIC)
    folded = unicodedata.normalize("NFKD", latin).encode("ascii", "ignore").decode("ascii")
    return _NOT_SLUG.sub("_", folded).strip("_")


def server_label(instance_name: str) -> str:
    """The server segment of a model-facing tool name. Idempotent."""
    name = instance_name.strip().lower()
    if name.isascii():
        return _sanitize(name) or "server"
    return ascii_slug(name) or "server"


def qualify_mcp_tool_name(label: str, raw_name: str) -> str:
    """``mcp__<label>__<raw>``, shortened with a stable digest past the provider limit."""
    name = _DELIMITER.join((_PREFIX, server_label(label), _sanitize(raw_name)))
    if len(name) <= MAX_TOOL_NAME_LENGTH:
        return name
    digest = hashlib.sha1(f"{label}\0{raw_name}".encode(), usedforsecurity=False).hexdigest()[:8]
    return f"{name[: MAX_TOOL_NAME_LENGTH - len(digest) - 1]}_{digest}"


@dataclass(frozen=True)
class McpToolIdentity:
    """The server and raw tool behind one model-facing MCP tool name."""

    model_name: str
    instance_id: str
    raw_name: str
    attachment_ref: str

    @property
    def canonical(self) -> str:
        """Stable across renames: the tool as ``mcp:<instance id>:<raw name>``."""
        return mcp_tool_target(self.instance_id, self.raw_name)

    @property
    def policy_names(self) -> tuple[str, ...]:
        """Names besides the model-facing one that a policy rule may target.

        An agent's approval rule names the tool through the agent's attachment,
        which may reference the server by name rather than id.
        """
        via_attachment = mcp_tool_target(self.attachment_ref, self.raw_name)
        if via_attachment == self.canonical:
            return (self.canonical,)
        return (self.canonical, via_attachment)

    @property
    def restricting_names(self) -> tuple[str, ...]:
        """Names that may deny the tool or hold it for approval, never allow it.

        The raw name is whatever the server advertises, so it cannot satisfy an
        allowlist: ``allowed: ["search"]`` would admit every attached server that
        calls a tool ``search``. A deny or approval rule naming ``search`` still
        reaches every server's ``search``.
        """
        return (self.raw_name,)


def mcp_tool_target(server_ref: str, raw_name: str) -> str:
    """How a policy rule names one tool of one attached server."""
    return f"{_PREFIX}:{server_ref}:{raw_name}"


_GLOB = re.compile(r"([*?\[])")


def mcp_tool_rule_target(instance_id: str, raw_name: str) -> str:
    """The rule target naming exactly this tool: targets match as fnmatch globs."""
    literal = _GLOB.sub(r"[\1]", raw_name)
    return f"tool:{mcp_tool_target(instance_id, literal)}"


def mcp_tool_policy_aliases(
    instance_id: str, instance_name: str | None, raw_name: str
) -> tuple[str, ...]:
    """The names a policy rule may give one tool of one MCP instance to allow it.

    The canonical ``mcp:<instance id>:<raw>``, the server referenced by name and
    the ``mcp__<server>__<raw>`` an agent calls it by. The raw name only narrows:
    see ``McpToolIdentity.restricting_names``.
    """
    names = [mcp_tool_target(instance_id, raw_name)]
    if instance_name:
        names += [
            mcp_tool_target(instance_name, raw_name),
            qualify_mcp_tool_name(instance_name, raw_name),
        ]
    return tuple(names)
