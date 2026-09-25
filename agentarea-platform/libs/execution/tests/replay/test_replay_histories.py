"""Recorded agent workflow histories replay against the current workflow code.

Production workers replay the histories of running workflows on every deploy,
so a change to the commands the workflow emits (activities, timers, child
workflows, patch markers) breaks runs already in flight. Each file in
``histories/`` is a run recorded from the integration scenarios; see
``tests/integration/conftest.py`` for how to record them. A history that stops
replaying means the change needs a ``workflow.patched`` gate, not a re-record.
"""

import json
from pathlib import Path

import pytest
from agentarea_common.workflow.sandbox import create_workflow_runner
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from temporalio.client import WorkflowHistory
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Replayer

HISTORIES = sorted((Path(__file__).parent / "histories").glob("*.json"))


def test_histories_are_recorded():
    assert len(HISTORIES) >= 30


@pytest.mark.parametrize("path", HISTORIES, ids=lambda path: path.stem)
async def test_recorded_history_replays(path: Path):
    recorded = json.loads(path.read_text())
    history = WorkflowHistory.from_json(recorded["workflow_id"], recorded["history"])

    await Replayer(
        workflows=[AgentExecutionWorkflow],
        data_converter=pydantic_data_converter,
        workflow_runner=create_workflow_runner(),
    ).replay_workflow(history)
