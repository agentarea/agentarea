from typing import Any, Literal

from typing_extensions import TypedDict

VERIFICATION_SCHEMA_VERSION = 1

DEFAULT_VERIFICATION: dict = {
    "schema_version": VERIFICATION_SCHEMA_VERSION,
    "status": "never_attempted",
    "at": None,
    "error": None,
}


class VerificationError(TypedDict):
    code: str
    message: str
    detail: str | dict[str, Any] | None


class VerificationPayload(TypedDict):
    schema_version: int
    status: Literal["never_attempted", "in_progress", "succeeded", "failed"]
    at: str | None
    error: VerificationError | None


class LastDispatchPayload(TypedDict):
    schema_version: int
    status: Literal["succeeded", "failed"]
    at: str
    error: str | None
