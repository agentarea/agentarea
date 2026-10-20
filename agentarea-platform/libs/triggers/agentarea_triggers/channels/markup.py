"""Task events as short chat messages, in the markup a reply block names (ADR-0040 section 5).

A markup flavour is how a chat renders bold, italic and quotes, and which emoji
codes it reads; the catalog entry's ``reply.markup`` picks one.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agentarea_common.events.contract import (
    APPROVAL_DECIDED,
    APPROVAL_REQUESTED,
    COMMAND_RECEIVED,
    DELEGATION_COMPLETED,
    DELEGATION_STARTED,
    TASK_CANCELLED,
    TASK_COMPLETED,
    TASK_FAILED,
    TASK_STARTED,
    TOOL_CALL,
    canonical_type,
)

from .exceptions import FatalError


@dataclass(frozen=True)
class MarkupFlavor:
    """How to render bold/italic/quote, the emoji map, and how text is escaped."""

    bold: tuple[str, str]
    italic: tuple[str, str]
    quote: str
    emojis: dict[str, str]
    escape: Callable[[str], str] | None = None


_COLON_EMOJIS = {
    "check": ":white_check_mark:",
    "cross": ":x:",
    "stop": ":no_entry_sign:",
    "question": ":question:",
    "hourglass": ":hourglass_flowing_sand:",
    "wrench": ":wrench:",
    "robot": ":robot_face:",
    "info": ":information_source:",
}

_UNICODE_EMOJIS = {
    "check": "\u2705",
    "cross": "\u274c",
    "stop": "\u26d4",
    "question": "\u2753",
    "hourglass": "\u23f3",
    "wrench": "\U0001f527",
    "robot": "\U0001f916",
    "info": "\u2139\ufe0f",
}


def _markdown_v2_escape(text: str) -> str:
    special = r"_*[]()~`>#+-=|{}.!\\"
    return "".join("\\" + c if c in special else c for c in text)


MARKUPS: dict[str, MarkupFlavor] = {
    "slack": MarkupFlavor(bold=("*", "*"), italic=("_", "_"), quote=">", emojis=_COLON_EMOJIS),
    "discord": MarkupFlavor(
        bold=("**", "**"), italic=("*", "*"), quote="> ", emojis=_UNICODE_EMOJIS
    ),
    "telegram": MarkupFlavor(
        bold=("*", "*"),
        italic=("_", "_"),
        quote=">",
        emojis=_UNICODE_EMOJIS,
        escape=_markdown_v2_escape,
    ),
    "plain": MarkupFlavor(bold=("", ""), italic=("", ""), quote="> ", emojis=_UNICODE_EMOJIS),
}


def markup(name: str) -> MarkupFlavor:
    flavor = MARKUPS.get(name)
    if flavor is None:
        raise FatalError(f"unknown reply markup {name!r}")
    return flavor


def format_event(flavor: MarkupFlavor, event: dict[str, Any], presentation: str) -> str:
    """One task event as one chat line in ``flavor``."""
    b0, b1 = flavor.bold
    i0, i1 = flavor.italic
    e = flavor.emojis
    esc = flavor.escape or (lambda t: t)

    raw_et = event.get("event_type", "")
    et = canonical_type(raw_et)
    d = event.get("data", {})

    if et == TASK_COMPLETED:
        return esc(str(d.get("final_response") or d.get("result") or ""))
    if et == TASK_FAILED:
        return f"{e['cross']} {b0}Failed{b1} \u2014 {esc(str(d.get('error', 'Unknown error')))}"
    if et == TASK_CANCELLED:
        return f"{e['stop']} {esc('Task was cancelled.')}"
    if et == APPROVAL_REQUESTED:
        q = esc(str(d.get("question", "Approval needed")))
        return f"{e['question']} {b0}Needs your input:{b1}\n{flavor.quote}{q}"
    if et == APPROVAL_DECIDED:
        approved = d.get("approved")
        if approved is True:
            return f"{e['check']} {esc('Approved, continuing...')}"
        if approved is False:
            comment = d.get("comment")
            reason = f" \u2014 {esc(str(comment))}" if comment else ""
            return f"{e['stop']} {b0}Denied{b1}{reason}"
        return f"{e['info']} {esc('Approval resolved.')}"

    if presentation == "concise":
        if et in (TASK_STARTED, COMMAND_RECEIVED):
            return f"{e['hourglass']} {esc('Working on it...')}"
        if et == TOOL_CALL:
            tool = d.get("tool_name", "tool")
            return f"{e['wrench']} {esc('Using ')}{i0}{esc(tool)}{i1}{esc('...')}"
        if et in (DELEGATION_STARTED, DELEGATION_COMPLETED):
            agent = d.get("agent_name", "sub-agent")
            action = "Delegating to" if et == DELEGATION_STARTED else "Received from"
            return f"{e['robot']} {action} {i0}{esc(agent)}{i1}"

    return f"{e['info']} {esc(raw_et)}"


def limited(flavor: MarkupFlavor, message: str, limit: int | None) -> str:
    """``message`` cut to ``limit`` characters, saying so in the flavour's own markup."""
    if limit is None or len(message) <= limit:
        return message
    i0, i1 = flavor.italic
    esc = flavor.escape or (lambda t: t)
    suffix = f"\n\n{i0}{esc('(truncated)')}{i1}"
    return message[: max(limit - len(suffix), 0)] + suffix


def strip_markup(text: str) -> str:
    """The text without lightweight markdown and escape markers, for a plain resend."""
    for marker in ("\\", "*", "_", "`"):
        text = text.replace(marker, "")
    return text
