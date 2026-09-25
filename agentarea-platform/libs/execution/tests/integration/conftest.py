"""Record agent workflow histories for the replay safety net in ``tests/replay``.

Run this directory with ``AGENTAREA_RECORD_REPLAY_HISTORIES=1``: every
``AgentExecutionWorkflow`` a test drives to a result, and every child it
started, is written to ``tests/replay/histories`` as its workflow id and
Temporal history JSON; the id is part of the replay because the workflow
derives child workflow ids from it. Record on the code whose
behaviour production histories were made with, before changing the workflow.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest
from temporalio.client import WorkflowFailureError, WorkflowHandle

HISTORIES_DIR = Path(__file__).parent.parent / "replay" / "histories"
_AGENT_WORKFLOW_TYPE = "AgentExecutionWorkflow"


def _workflow_type(history) -> str:
    return history.events[0].workflow_execution_started_event_attributes.workflow_type.name


@pytest.fixture(autouse=True)
def _record_replay_histories(request, monkeypatch):
    if not os.environ.get("AGENTAREA_RECORD_REPLAY_HISTORIES"):
        yield
        return

    original_result = WorkflowHandle.result
    stem = re.sub(r"[^A-Za-z0-9_]+", "_", f"{request.path.stem}__{request.node.name}").strip("_")
    recorded: list[str] = []

    async def save(handle: WorkflowHandle) -> None:
        client = handle._client
        candidates = [handle, client.get_workflow_handle(handle.id)]
        for candidate in candidates:
            history = await candidate.fetch_history()
            for event in history.events:
                if event.HasField("child_workflow_execution_started_event_attributes"):
                    child = event.child_workflow_execution_started_event_attributes
                    candidates.append(
                        client.get_workflow_handle(
                            child.workflow_execution.workflow_id,
                            run_id=child.workflow_execution.run_id,
                        )
                    )
            if _workflow_type(history) != _AGENT_WORKFLOW_TYPE:
                continue
            content = json.dumps(
                {"workflow_id": history.workflow_id, "history": history.to_json_dict()},
                separators=(",", ":"),
            )
            if content in recorded:
                continue
            recorded.append(content)
            HISTORIES_DIR.mkdir(parents=True, exist_ok=True)
            (HISTORIES_DIR / f"{stem}__{len(recorded)}.json").write_text(content)

    async def result(self, *args, **kwargs):
        try:
            value = await original_result(self, *args, **kwargs)
        except WorkflowFailureError:
            await save(self)
            raise
        await save(self)
        return value

    monkeypatch.setattr(WorkflowHandle, "result", result)
    yield
