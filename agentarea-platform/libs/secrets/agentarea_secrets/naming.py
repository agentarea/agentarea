"""Secret name rules: reading platform-minted names, and keeping users out of them.

Every producer on the platform builds its secret name from the id of whatever
owns the secret. Those names predate the catalog, so the catalog learns who owns
a row by parsing them rather than by a column that was never written. The same
patterns are what users must not be able to type: `(workspace_id, secret_name)`
is unique, so a colliding name is an update to someone else's secret, not a new
one.
"""

import re
from typing import NamedTuple

# Every prefix a platform producer mints names under. Adding a producer means
# adding it here and to _PARSERS; test_every_producer_prefix_is_actually_reserved
# holds the two together.
RESERVED_PREFIXES: tuple[str, ...] = (
    "provider_config_",
    "mcp_instance_",
    "mcp_auth_cred:",
    "channel_cred:",
    "wallet_creds_",
    "openapi:",
    "task-input/",
    "a2a_push_token:",
)

_USER_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}[a-z0-9]$")

_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_UUID_LEN = 36


class SecretNameError(ValueError):
    """A user-supplied secret name the catalog will not accept."""


class ReservedSecretNameError(SecretNameError):
    """The name belongs to the space platform producers mint into."""


class OwnerRef(NamedTuple):
    owner_type: str
    owner_id: str


def _uuid_at_start(rest: str) -> str | None:
    """Return the uuid rest begins with, if it does."""
    candidate = rest[:_UUID_LEN]
    return candidate if _UUID_RE.fullmatch(candidate) else None


def _parse_provider_config(rest: str) -> OwnerRef | None:
    return OwnerRef("provider_config", rest) if _UUID_RE.fullmatch(rest) else None


def _parse_mcp_instance(rest: str) -> OwnerRef | None:
    # `mcp_instance_{uuid}_{env_name}`, and env names contain underscores too.
    # The uuid's fixed width is the only thing separating them.
    instance_id = _uuid_at_start(rest)
    if instance_id is None or not rest[_UUID_LEN:].startswith("_"):
        return None
    return OwnerRef("mcp_instance", instance_id)


def _parse_mcp_auth_cred(rest: str) -> OwnerRef | None:
    return OwnerRef("mcp_auth_config", rest) if _UUID_RE.fullmatch(rest) else None


def _parse_channel_cred(rest: str) -> OwnerRef | None:
    # `channel_cred:{channel_type}:{trigger_id}` — the channel type is a plain
    # word, so splitting from the right survives it.
    _, separator, trigger_id = rest.rpartition(":")
    if not separator or not _UUID_RE.fullmatch(trigger_id):
        return None
    return OwnerRef("trigger", trigger_id)


def _parse_wallet_creds(rest: str) -> OwnerRef | None:
    return OwnerRef("agent", rest) if _UUID_RE.fullmatch(rest) else None


def _parse_openapi(rest: str) -> OwnerRef | None:
    # `openapi:{connection_id}:header:{header_name}`, and header names may
    # themselves contain colons, so read the id off the front.
    connection_id = _uuid_at_start(rest)
    if connection_id is None or not rest[_UUID_LEN:].startswith(":header:"):
        return None
    return OwnerRef("openapi_connection", connection_id)


def _parse_task_input(rest: str) -> OwnerRef | None:
    task_id, separator, _ = rest.partition("/")
    if not separator or not _UUID_RE.fullmatch(task_id):
        return None
    return OwnerRef("task", task_id)


def _parse_a2a_push_token(rest: str) -> OwnerRef | None:
    # `a2a_push_token:{task_id}:{config_id}`. Only the task id is ours — the
    # config id comes from the client's A2A pushNotificationConfig, which may be
    # any string it likes. Requiring it to be a uuid made a client able to mint
    # an unparseable name, and the catalog backfill refuses to migrate one of
    # those, so a single API call could have blocked every future deploy.
    task_id, separator, config_id = rest.partition(":")
    if not separator or not config_id or not _UUID_RE.fullmatch(task_id):
        return None
    return OwnerRef("task", task_id)


_PARSERS = (
    ("provider_config_", _parse_provider_config),
    ("mcp_instance_", _parse_mcp_instance),
    ("mcp_auth_cred:", _parse_mcp_auth_cred),
    ("channel_cred:", _parse_channel_cred),
    ("wallet_creds_", _parse_wallet_creds),
    ("openapi:", _parse_openapi),
    ("task-input/", _parse_task_input),
    ("a2a_push_token:", _parse_a2a_push_token),
)


def has_reserved_prefix(name: str) -> bool:
    """Whether the name claims to belong to a platform producer."""
    return name.startswith(RESERVED_PREFIXES)


def parse_managed_name(name: str) -> OwnerRef | None:
    """Read a platform-minted name back into the owner it was built from.

    Returns None when the name matches no producer. Callers must decide what
    that means rather than assume: the catalog backfill treats it as a row it
    cannot place and stops, instead of guessing an owner.
    """
    for prefix, parser in _PARSERS:
        if name.startswith(prefix):
            return parser(name[len(prefix) :])
    return None


def validate_user_secret_name(name: str) -> None:
    """Raise unless the name is one a user may claim.

    Reserved prefixes are checked first. They also fail the slug pattern, and
    reporting one as merely malformed would send the user off to adjust
    punctuation on a name they are never allowed to have.
    """
    if has_reserved_prefix(name):
        prefix = next(p for p in RESERVED_PREFIXES if name.startswith(p))
        raise ReservedSecretNameError(
            f"Secret name may not start with '{prefix}': that prefix is reserved for "
            "secrets the platform manages on behalf of a connection."
        )

    if not _USER_NAME_RE.fullmatch(name):
        raise SecretNameError(
            f"Invalid secret name '{name}'. Use 2-64 characters: lowercase letters, digits, "
            "'-' and '_', starting and ending with a letter or digit."
        )
