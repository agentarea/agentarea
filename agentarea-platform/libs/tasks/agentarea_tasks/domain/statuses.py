"""The statuses a task record can be stored with, and the inbox's subset of them.

One vocabulary for the validator, the task list filter, the inbox router and the
inbox tool. As ``Literal`` types they also publish the list in the OpenAPI
schema, so the generated client carries it.
"""

from typing import Literal, get_args

TaskStatus = Literal[
    "submitted",
    "pending",
    "preparing",
    "scheduled",
    "running",
    "working",
    "waiting_for_input",
    "waiting_for_approval",
    "waiting_for_continuation",
    "blocked",
    "completed",
    "failed",
    "cancelled",
]
TASK_STATUSES: frozenset[str] = frozenset(get_args(TaskStatus))

InboxStatus = Literal[
    "waiting_for_approval",
    "waiting_for_input",
    "completed",
    "failed",
]
INBOX_STATUSES: tuple[str, ...] = get_args(InboxStatus)
