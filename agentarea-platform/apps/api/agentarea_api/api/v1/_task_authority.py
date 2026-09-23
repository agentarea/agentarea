"""Who may act on a run in progress.

Starting a task is a workspace-member action: you use an agent you can see.
Acting on a task that is *already running* -- answering its question, sending it
a command, pausing, cancelling, deleting it -- is not. That run belongs to
whoever started it, and until 2026-09-23 the only thing standing between an
invited member and somebody else's conversation was the workspace column, which
they are on the same side of.

The task is not a ``resource:`` object in the graph and should not become one:
there is one row per run, the tuple volume would dwarf everything else, and the
question has a cheaper answer that is already on the row -- ``created_by``. A
workspace admin passes too, because the person who owns the workspace has to be
able to stop a run that is spending its money.
"""

from __future__ import annotations

from uuid import UUID

from agentarea_common.auth.authorization import assert_workspace_admin
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.auth.route_authz import AUTHZ_ATTR
from agentarea_tasks.task_service import TaskService
from fastapi import Depends, params

from ..deps.services import get_task_service


async def assert_may_act_on_task(task, user_context: UserContext) -> None:
    """Raise 403 unless the caller started this run, or administers the workspace."""
    creator = getattr(task, "user_id", None) or getattr(task, "created_by", None)
    if creator and str(creator) == str(user_context.user_id):
        return
    # Not the creator: the only other answer is authority over the workspace,
    # which raises 403 of its own if it is not there.
    await assert_workspace_admin(user_context)


def requires_task_authority() -> params.Depends:
    """Gate a route on the run's ownership, resolved from its path ``task_id``.

    A route-level dependency rather than a line in each handler: the eleven
    task-write endpoints load the task in four different ways (or not at all),
    and a check that has to be remembered per handler is the thing that was
    missing in the first place.

    It resolves the task through the same ``get_task_service`` the handlers use,
    so a test that overrides that dependency covers the guard too rather than
    falling through to a real database.
    """

    async def _check(
        task_id: UUID,
        user_context: UserContextDep,
        task_service: TaskService = Depends(get_task_service),
    ) -> None:
        task = await task_service.get_task(task_id)
        if task is None:
            # Let the handler answer 404 with its own wording; refusing here
            # would turn "no such task" into "not yours", which leaks whether
            # the id exists.
            return
        await assert_may_act_on_task(task, user_context)

    setattr(_check, AUTHZ_ATTR, {"action": "operate", "resource_type": "task"})
    return Depends(_check)


__all__ = ["assert_may_act_on_task", "requires_task_authority"]
