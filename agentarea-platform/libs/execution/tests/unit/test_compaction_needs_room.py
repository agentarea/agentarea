"""A compaction that could free nothing worth a paid summary is not run again."""

import pytest
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from agentarea_execution.workflows.context_manager import ContextWindowManager
from temporalio import workflow


@pytest.fixture
def instance(monkeypatch):
    monkeypatch.setattr(workflow, "patched", lambda _patch_id: True)
    monkeypatch.setattr(workflow, "logger", type("L", (), {"warning": lambda *a, **k: None})())
    run = AgentExecutionWorkflow()
    run.context_manager = ContextWindowManager(10_000)
    return run


@pytest.mark.asyncio
async def test_a_context_whose_fixed_part_fills_the_window_is_not_compacted_every_turn(instance):
    calls: list[object] = []

    async def compaction(request):
        calls.append(request)
        raise AssertionError("no compaction should run")

    instance._run_compaction_activity = compaction
    instance._awaiting_compaction_floor = True
    instance._note_prompt_tokens(8_000)
    instance.context_manager.update_usage(8_200)

    assert await instance._compact_context_if_needed() is False
    assert calls == []


def test_the_floor_is_the_first_prompt_measured_after_a_compaction(instance):
    instance._awaiting_compaction_floor = True

    instance._note_prompt_tokens(3_000)
    instance._note_prompt_tokens(5_000)

    assert instance._compaction_floor_tokens == 3_000

