"""Unit tests for the canonical event contract.

Pure tests: no Redis, no DB. They lock the public API of
``agentarea_common.events.contract``:

- ``canonical_type`` — identity for canonical inputs, strips a defensive
  ``workflow.`` prefix. There is no legacy alias bridge.
- ``derive_part`` — map a canonical (event_type, data) to a superseding Part.
- ``reduce_parts`` — supersede-by-id fold over an event stream.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from agentarea_common.events.contract import (
    Part,
    canonical_type,
    derive_part,
    reduce_parts,
)


class TestCanonicalType:
    def test_canonical_inputs_pass_through(self):
        for t in (
            "llm.call.started",
            "llm.call.completed",
            "llm.call.failed",
            "llm.call.chunk",
            "tool.call",
            "tool.result",
            "input.request",
            "input.response",
            "approval.request",
            "approval.response",
            "artifact.created",
            "task.started",
            "task.completed",
            "task.failed",
            "task.cancelled",
        ):
            assert canonical_type(t) == t

    def test_strips_defensive_workflow_prefix(self):
        assert canonical_type("workflow.task.completed") == "task.completed"
        assert canonical_type("workflow.llm.call.chunk") == "llm.call.chunk"

    def test_unknown_type_is_identity(self):
        # No alias table: anything not workflow.-prefixed is returned unchanged.
        assert canonical_type("BudgetWarning") == "BudgetWarning"
        assert canonical_type("IterationStarted") == "IterationStarted"

    def test_idempotent(self):
        for t in (
            "llm.call.chunk",
            "tool.result",
            "task.completed",
            "workflow.task.completed",
        ):
            assert canonical_type(canonical_type(t)) == canonical_type(t)


class TestDeriveTool:
    def test_tool_call_part(self):
        part = derive_part(
            "tool.call",
            {"tool_name": "shell", "tool_call_id": "tc-1", "arguments": {}},
        )
        assert part is not None
        assert part.kind == "tool"
        assert part.part_id == "tc-1"
        assert part.event_type == "tool.call"

    def test_tool_result_supersedes_tool_call_same_id(self):
        call = derive_part("tool.call", {"tool_call_id": "tc-9"})
        result = derive_part("tool.result", {"tool_call_id": "tc-9"})
        assert call is not None
        assert result is not None
        assert call.part_id == result.part_id == "tc-9"
        assert call.kind == result.kind == "tool"
        assert result.event_type == "tool.result"


class TestDeriveLLM:
    def test_llm_started_part_id_from_execution_and_iteration(self):
        part = derive_part(
            "llm.call.started",
            {"execution_id": "exec-1", "iteration": 2, "message_count": 3},
        )
        assert part is not None
        assert part.kind == "llm"
        assert part.part_id == "exec-1:2"
        assert part.event_type == "llm.call.started"

    def test_chunk_and_final_share_part_id(self):
        chunk = derive_part(
            "llm.call.chunk",
            {"execution_id": "exec-1", "iteration": 2, "chunk": "he", "chunk_index": 0},
        )
        final = derive_part(
            "llm.call.completed",
            {"execution_id": "exec-1", "iteration": 2, "content": "hello"},
        )
        assert chunk is not None
        assert final is not None
        assert chunk.part_id == final.part_id == "exec-1:2"
        assert chunk.event_type == "llm.call.chunk"
        assert final.event_type == "llm.call.completed"


class TestDeriveForm:
    def test_input_request_uses_input_request_id(self):
        part = derive_part(
            "input.request",
            {"input_request_id": "ir-1", "question": "name?"},
        )
        assert part is not None
        assert part.kind == "form"
        assert part.part_id == "ir-1"
        assert part.event_type == "input.request"

    def test_input_response_supersedes_by_same_id(self):
        req = derive_part("input.request", {"input_request_id": "ir-7"})
        resp = derive_part("input.response", {"input_request_id": "ir-7"})
        assert req is not None
        assert resp is not None
        assert req.part_id == resp.part_id == "ir-7"
        assert req.kind == resp.kind == "form"

    def test_input_request_falls_back_to_request_id(self):
        part = derive_part("input.request", {"request_id": "rq-2"})
        assert part is not None
        assert part.part_id == "rq-2"

    def test_approval_uses_escalation_id(self):
        part = derive_part(
            "approval.request",
            {"escalation_id": "esc-1", "tool_name": "shell"},
        )
        assert part is not None
        assert part.kind == "form"
        assert part.part_id == "esc-1"
        assert part.event_type == "approval.request"

    def test_approval_response_supersedes(self):
        req = derive_part("approval.request", {"escalation_id": "esc-3"})
        resp = derive_part("approval.response", {"escalation_id": "esc-3"})
        assert req is not None
        assert resp is not None
        assert req.part_id == resp.part_id == "esc-3"
        assert req.kind == resp.kind == "form"


class TestDeriveArtifact:
    def test_artifact_uses_artifact_id(self):
        part = derive_part(
            "artifact.created",
            {"artifact_id": "art-1", "name": "deck.pptx"},
        )
        assert part is not None
        assert part.kind == "artifact"
        assert part.part_id == "art-1"
        assert part.event_type == "artifact.created"


class TestDeriveLifecycle:
    def test_task_events_return_none(self):
        for t in (
            "task.created",
            "task.started",
            "task.updated",
            "task.completed",
            "task.failed",
            "task.cancelled",
        ):
            assert derive_part(t, {"message": "x"}) is None


class TestReduceParts:
    def test_chunks_then_final_collapse_to_one_final(self):
        events = [
            ("llm.call.chunk", {"execution_id": "e", "iteration": 1, "chunk": "h", "chunk_index": 0}),
            ("llm.call.chunk", {"execution_id": "e", "iteration": 1, "chunk": "i", "chunk_index": 1}),
            ("llm.call.completed", {"execution_id": "e", "iteration": 1, "content": "hi"}),
        ]
        parts = reduce_parts(events)
        assert len(parts) == 1
        assert parts[0].event_type == "llm.call.completed"
        assert parts[0].part_id == "e:1"

    def test_form_supersede_two_requests_same_id(self):
        events = [
            ("input.request", {"input_request_id": "ir-1", "question": "a?"}),
            ("input.response", {"input_request_id": "ir-1"}),
        ]
        parts = reduce_parts(events)
        assert len(parts) == 1
        assert parts[0].kind == "form"

    def test_lifecycle_events_skipped(self):
        events = [
            ("task.created", {"message": "created"}),
            ("tool.call", {"tool_call_id": "tc-1"}),
            ("task.completed", {"message": "done"}),
        ]
        parts = reduce_parts(events)
        assert len(parts) == 1
        assert parts[0].part_id == "tc-1"

    def test_order_preserved_supersede_in_place(self):
        events = [
            ("tool.call", {"tool_call_id": "tc-1"}),
            ("input.request", {"input_request_id": "ir-1"}),
            ("tool.result", {"tool_call_id": "tc-1"}),
        ]
        parts = reduce_parts(events)
        assert [p.part_id for p in parts] == ["tc-1", "ir-1"]
        assert parts[0].event_type == "tool.result"

    def test_out_of_order_and_duplicate_ids_idempotent(self):
        events = [
            ("tool.result", {"tool_call_id": "tc-1"}),
            ("tool.result", {"tool_call_id": "tc-1"}),
            ("tool.call", {"tool_call_id": "tc-1"}),
        ]
        parts = reduce_parts(events)
        assert len(parts) == 1
        assert parts[0].part_id == "tc-1"
        assert parts[0].event_type == "tool.call"


class TestPart:
    def test_part_is_frozen(self):
        part = Part(part_id="p1", kind="tool", event_type="tool.call", data={})
        with pytest.raises(FrozenInstanceError):
            part.part_id = "p2"  # type: ignore[misc]
