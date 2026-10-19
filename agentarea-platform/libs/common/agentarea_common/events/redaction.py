"""How a tool call's arguments and result appear in the event log: bounded, without secrets."""

import re
from typing import Any

_EVENT_CONTENT_KEYS = frozenset(
    {
        "base64",
        "blob",
        "body",
        "bytes",
        "code",
        "content",
        "contents",
        "data",
        "file_content",
        "payload",
        "result",
        "script",
        "stderr",
        "stdout",
    }
)
_EVENT_SECRET_KEYS = frozenset(
    {"api_key", "authorization", "credential", "password", "secret", "token"}
)
_BASE64_LIKE = re.compile(r"^[A-Za-z0-9+/=_-]{256,}$")
MAX_EVENT_STRING_CHARS = 2000


def _event_omission(value: Any) -> str:
    size = len(value) if isinstance(value, str | bytes | bytearray) else 0
    return f"[omitted from event log: {size} units]"


def _looks_binary_or_bulk(value: str) -> bool:
    if len(value) > MAX_EVENT_STRING_CHARS or _BASE64_LIKE.fullmatch(value):
        return True
    if "\x00" in value:
        return True
    controls = sum(ord(character) < 32 and character not in "\n\r\t" for character in value)
    return bool(value) and controls / len(value) > 0.02


def sanitize_tool_event_value(value: Any, *, field_name: str = "", _depth: int = 0) -> Any:
    """Bound event metadata without file bodies, secrets, or binary blobs.

    This helper applies only to Redis/DB event projections. Activities and the
    LLM still receive the original tool arguments and results.
    """
    if _depth >= 10:
        return "[nested value omitted from event log]"
    normalized_name = field_name.lower()
    if any(fragment in normalized_name for fragment in _EVENT_SECRET_KEYS):
        return "[redacted]"
    if normalized_name in _EVENT_CONTENT_KEYS:
        return _event_omission(value)
    if normalized_name == "command":
        return _event_omission(value)
    if isinstance(value, str):
        return _event_omission(value) if _looks_binary_or_bulk(value) else value
    if isinstance(value, bytes | bytearray):
        return _event_omission(value)
    if isinstance(value, dict):
        return {
            str(key): sanitize_tool_event_value(item, field_name=str(key), _depth=_depth + 1)
            for key, item in list(value.items())[:100]
        }
    if isinstance(value, list | tuple):
        return [sanitize_tool_event_value(item, _depth=_depth + 1) for item in value[:100]]
    if value is None or isinstance(value, bool | int | float):
        return value
    return f"[{type(value).__name__} omitted from event log]"


_REDACTED = "[redacted]"
_VALUE = r"""(?:"[^"]*"|'[^']*'|[^\s,;&'"}\]]+)"""
_AUTHORIZATION = re.compile(
    r"(?i)\b((?:proxy-)?authorization\s*[:=]\s*)(?:(bearer|basic|token|digest)\s+)?([^\s'\",]+)"
)
_BEARER = re.compile(r"(?i)\b(bearer\s+)([A-Za-z0-9._~+/=-]{8,})")
_FLAG = re.compile(rf"(?<![\w-])(--?)([A-Za-z][\w-]*)(=|\s+)({_VALUE})")
_ASSIGNMENT = re.compile(rf"""(["']?)([A-Za-z_][\w.-]*)\1(\s*[:=]\s*)({_VALUE})""")
_URL_USERINFO = re.compile(r"(\b[a-zA-Z][\w+.-]*://[^/\s:@]+:)([^/\s@]+)(@)")
_USER_FLAG = re.compile(r"""((?<!\S)(?:-u|--user)[\s=]+['"]?[^:\s'"]+:)([^\s'"]+)""")
_MYSQL_PASSWORD = re.compile(r"(\b(?:mysql|mysqldump|mysqladmin|mariadb)\b[^|;&\n]*?\s-p)(\S+)")
_SSHPASS = re.compile(r"(\bsshpass\s+-p\s+)(\S+)")
_TOKEN_SHAPES = re.compile(
    r"\b(?:(?:sk|rk)-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|xox[abposr]-[A-Za-z0-9-]{10,}"
    + r"|AKIA[0-9A-Z]{16})\b"
)


def _secret_name(name: str) -> bool:
    normalized = name.lower().replace("-", "_")
    return "passwd" in normalized or any(fragment in normalized for fragment in _EVENT_SECRET_KEYS)


def _masked_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return f"{value[0]}{_REDACTED}{value[0]}"
    return _REDACTED


def _mask_named(match: re.Match[str], name_group: int, value_group: int) -> str:
    name = match.group(name_group).lower()
    # An Authorization header keeps its scheme; ``_AUTHORIZATION`` masked its credential.
    if not _secret_name(name) or name.endswith("authorization"):
        return match.group(0)
    start, end = match.span(value_group)
    whole = match.group(0)
    offset = match.start(0)
    return whole[: start - offset] + _masked_value(match.group(value_group)) + whole[end - offset :]


def _mask_authorization(match: re.Match[str]) -> str:
    scheme = f"{match.group(2)} " if match.group(2) else ""
    return f"{match.group(1)}{scheme}{_REDACTED}"


def mask_inline_secrets(text: str) -> str:
    """``text`` with the secret-shaped parts masked in place and everything else kept.

    Masks an Authorization header's credential, a bearer token, the value of a
    flag or ``key=value`` / ``"key": value`` whose name is secret-shaped (the
    names the event log redacts), a password in a URL or ``-u user:pass``,
    mysql's ``-p<password>``, sshpass's ``-p``, and well-known token shapes.
    """
    masked = _AUTHORIZATION.sub(_mask_authorization, text)
    masked = _BEARER.sub(lambda m: f"{m.group(1)}{_REDACTED}", masked)
    masked = _FLAG.sub(lambda m: _mask_named(m, 2, 4), masked)
    masked = _ASSIGNMENT.sub(lambda m: _mask_named(m, 2, 4), masked)
    masked = _URL_USERINFO.sub(lambda m: f"{m.group(1)}{_REDACTED}{m.group(3)}", masked)
    masked = _USER_FLAG.sub(lambda m: f"{m.group(1)}{_REDACTED}", masked)
    masked = _MYSQL_PASSWORD.sub(lambda m: f"{m.group(1)}{_REDACTED}", masked)
    masked = _SSHPASS.sub(lambda m: f"{m.group(1)}{_REDACTED}", masked)
    return _TOKEN_SHAPES.sub(_REDACTED, masked)


def reveal_tool_value(value: Any, *, field_name: str = "", _depth: int = 0) -> Any:
    """A tool call's arguments or result as the task's authority sees them.

    Whole, unlike ``sanitize_tool_event_value``: a command and an output are
    kept, with a secret-shaped key's value and the secrets inside a text masked.
    """
    if _depth >= 10:
        return "[nested value omitted from event log]"
    if field_name and _secret_name(field_name):
        return _REDACTED
    if isinstance(value, str):
        return mask_inline_secrets(value)
    if isinstance(value, bytes | bytearray):
        return _event_omission(value)
    if isinstance(value, dict):
        return {
            str(key): reveal_tool_value(item, field_name=str(key), _depth=_depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [reveal_tool_value(item, _depth=_depth + 1) for item in value]
    if value is None or isinstance(value, bool | int | float):
        return value
    return f"[{type(value).__name__} omitted from event log]"
