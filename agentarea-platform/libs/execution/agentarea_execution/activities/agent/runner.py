"""Hand a message or an approval answer to the runner holding a task's turn (ADR-0051)."""

from collections.abc import Callable
from typing import Any

from temporalio import activity

from ...interfaces import ActivityDependencies
from ...models import DeliverToRunnerRequest


def runner_channel(client_id: str) -> str:
    """The broadcast channel every socket of the client's runners listens on."""
    return f"clients.{client_id}.runner"


def make_runner_activities(dependencies: ActivityDependencies) -> list[Callable[..., Any]]:
    @activity.defn
    async def deliver_to_runner_activity(request: DeliverToRunnerRequest) -> None:
        """Broadcast it to the client's runner sockets; the one holding the turn passes it on.

        A message no runner takes stays with the run, which sends it as the next turn.
        """
        broker = dependencies.broker_client
        if broker is None:
            raise RuntimeError("delivering to a runner needs a broker client")
        fields = {
            key: str(value).lower() if isinstance(value, bool) else str(value)
            for key, value in request.model_dump(exclude={"client_id"}).items()
            if value is not None
        }
        await broker.notify(runner_channel(request.client_id), fields)

    return [deliver_to_runner_activity]
