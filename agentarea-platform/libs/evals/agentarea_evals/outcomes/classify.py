"""What a finished run counts as when revisions are compared."""

from collections.abc import Iterable
from enum import StrEnum


class Outcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    # Not the agent's verdict to give: the user stopped it.
    EXCLUDED = "excluded"
    # Still running, or waiting on a person; not counted yet.
    PENDING = "pending"


_SUCCESS = {"completed", "awaiting_follow_up"}
# waiting_for_continuation is the iteration cap: the run did not converge.
_FAILURE = {"failed", "waiting_for_continuation"}
_EXCLUDED = {"cancelled", "canceled"}
_PENDING = {
    "pending",
    "submitted",
    "scheduled",
    "preparing",
    "running",
    "routed",
    "blocked",
    "paused",
    "waiting_for_input",
    "waiting_for_approval",
}


def classify(status: str, ratings: Iterable[str]) -> Outcome:
    """Classify a run by its status and the human ratings it received.

    A ``bad`` rating fails a run that finished; nothing rescues a failed one.
    """
    if status in _PENDING:
        return Outcome.PENDING
    if status in _EXCLUDED:
        return Outcome.EXCLUDED
    if status in _FAILURE:
        return Outcome.FAILURE
    if status in _SUCCESS:
        return Outcome.FAILURE if "bad" in set(ratings) else Outcome.SUCCESS
    raise ValueError(f"unknown task status {status!r}")
