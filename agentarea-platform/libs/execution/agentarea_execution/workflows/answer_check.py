"""Last look at an agent's final answer before a person reads it.

A fast model still slips: CJK characters in a Russian answer, a tool's name, a
snake_case code, a stack trace, raw JSON, a stray English word. A cheap
deterministic check finds those; only then does the workflow spend one silent
rewrite call asking the same model to fix exactly those things.

Pure stdlib, safe in the Temporal sandbox. Turned on per agent (or workspace)
by a governance ``safety`` rule on ``content`` with ``params.answer_check``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯豈-﫿]+")
_STACK = re.compile(
    r"(?:^|\s)at\s+\S+\s+\(?/|node_modules/|Traceback \(most recent call last\)"
    r"|\b(?:TypeError|ReferenceError|SyntaxError|ENOENT)\b|\bError:\s",
    re.MULTILINE,
)
_JSON_LIKE = re.compile(r'\{\s*"[A-Za-z_]+"\s*:')
_IDENTIFIER = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
# Lowercase Latin words are developer words in a Russian answer; brands are
# capitalised and abbreviations upper-case.
_ENGLISH_WORD = re.compile(r"(?<![\w./-])[a-z]{4,}(?!\w)")
_ALLOWED_WORDS = frozenset({"xlsx", "docx", "html", "http", "https", "mailto"})
_CYRILLIC = re.compile(r"[Ѐ-ӿ]")
_LETTER = re.compile(r"[^\W\d_]")
_URL = re.compile(r"https?://[^\s)]+|/api/[^\s)]+")
# Answers in these languages are written in CJK, so CJK is not a leak there.
_CJK_LANGUAGES = frozenset({"zh", "ja", "ko"})

_SAMPLE_LENGTH = 80


@dataclass(frozen=True)
class Leak:
    kind: str  # cjk | tool_name | identifier | stack_trace | json | english
    sample: str

    def as_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "sample": self.sample}


def answer_check_config(effective_policy: dict[str, Any] | None) -> dict[str, Any] | None:
    """The enabled answer check of a run's effective policy, or None."""
    safety = (effective_policy or {}).get("content_safety") or {}
    config = safety.get("answer_check")
    if not isinstance(config, dict) or config.get("enabled") is False:
        return None
    return config


def _prose_only(text: str) -> str:
    """Links, file names and code blocks are the person's data, not our wording."""
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"\]\([^)]*\)", "]", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"/api/\S+", " ", text)
    return re.sub(
        r"[\w.\- ]+\.(?:xlsx|xls|pdf|docx|csv|jpe?g|png)\b", " ", text, flags=re.IGNORECASE
    )


def _mostly_cyrillic(text: str) -> bool:
    letters = len(_LETTER.findall(text))
    return letters > 0 and len(_CYRILLIC.findall(text)) * 2 >= letters


def find_leaks(text: str, tool_names: list[str], language: str | None) -> list[Leak]:
    """What in ``text`` a person should not have to read.

    The English-word check runs only for ``language == "ru"`` and an answer that
    is mostly Cyrillic: in an English answer every word would match.
    """
    prose = _prose_only(text)
    leaks: list[Leak] = []

    def add(kind: str, match: re.Match[str] | None) -> None:
        if match:
            leaks.append(Leak(kind, match.group(0).strip()[:_SAMPLE_LENGTH]))

    if language not in _CJK_LANGUAGES:
        add("cjk", _CJK.search(prose))
    for name in tool_names:
        if name and re.search(rf"\b{re.escape(name)}\b", prose):
            leaks.append(Leak("tool_name", name[:_SAMPLE_LENGTH]))
            break
    add("stack_trace", _STACK.search(prose))
    add("json", _JSON_LIKE.search(prose))
    if not any(leak.kind == "tool_name" for leak in leaks):
        add("identifier", _IDENTIFIER.search(prose))
    if language == "ru" and _mostly_cyrillic(prose):
        english = next(
            (m for m in _ENGLISH_WORD.finditer(prose) if m.group(0) not in _ALLOWED_WORDS), None
        )
        add("english", english)
    return leaks


def tool_names_of(available_tools: list[dict[str, Any]]) -> list[str]:
    """The names a model could quote: each tool's name and, for MCP, its raw name."""
    names: list[str] = []
    for tool in available_tools:
        name = (tool.get("function") or {}).get("name") or tool.get("name")
        if not isinstance(name, str) or not name:
            continue
        names.append(name)
        if name.startswith("mcp__"):
            raw = name.rsplit("__", 1)[-1]
            if raw and raw not in names:
                names.append(raw)
    return names


_REWRITE_SYSTEM = {
    "ru": (
        "Ты редактор ответов ассистента. Перепиши ответ для человека:\n"
        "- тот же смысл, все цифры, суммы, ссылки и названия файлов — дословно, "
        "markdown-ссылки не трогай;\n"
        "- только по-русски: переведи английские слова, убери иероглифы;\n"
        "- убери названия инструментов, коды и ключи (snake_case), JSON, тексты ошибок "
        "и стек-трейсы — скажи по-человечески, что произошло, если это важно;\n"
        "- не добавляй нового и не сокращай по смыслу.\n"
        "Верни только исправленный текст ответа."
    ),
    None: (
        "You edit an assistant's answer for the person reading it. Rewrite it:\n"
        "- same meaning; every number, amount, link and file name verbatim; leave "
        "markdown links as they are;\n"
        "- in the answer's own language; remove characters from other scripts;\n"
        "- remove tool names, codes and keys (snake_case), JSON, error texts and stack "
        "traces; say plainly what happened if it matters;\n"
        "- add nothing and drop nothing of substance.\n"
        "Return only the corrected answer."
    ),
}


def rewrite_messages(
    text: str, leaks: list[Leak], language: str | None, instruction: str | None
) -> list[dict[str, str]]:
    """The one rewrite call: what is wrong, and the answer to fix."""
    system = instruction or _REWRITE_SYSTEM.get(language) or _REWRITE_SYSTEM[None]
    found = ", ".join(f"{leak.kind} «{leak.sample}»" for leak in leaks)
    if language == "ru":
        prompt = f"Что не так: {found}.\n\nОтвет:\n{text}"  # noqa: RUF001
    else:
        prompt = f"What is wrong: {found}.\n\nAnswer:\n{text}"
    return [{"role": "system", "content": system}, {"role": "user", "content": prompt}]


def accept_rewrite(original: str, rewritten: str | None, *, strip_cjk: bool) -> str | None:
    """The rewrite if it is usable: not empty and every link of the original kept."""
    candidate = (rewritten or "").strip()
    if not candidate:
        return None
    if any(link not in candidate for link in _URL.findall(original)):
        return None
    return strip_unreadable(candidate) if strip_cjk else candidate


def strip_unreadable(text: str) -> str:
    """Deterministic floor: CJK characters, which the reader cannot read, go."""
    return re.sub(r" {2,}", " ", _CJK.sub("", text))
