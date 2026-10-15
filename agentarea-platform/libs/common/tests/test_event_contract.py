"""Unit tests for the canonical event contract.

Pure tests: no Redis, no DB. They lock the public API of
``agentarea_common.events.contract``:

- ``canonical_type`` — identity for canonical inputs, strips the ``workflow.``
  namespace prefix. There is no alias bridge.
- ``derive_part`` — map a canonical (event_type, data) to a superseding Part.
- ``reduce_parts`` — supersede-by-id fold over an event stream.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from agentarea_common.events.contract import (
    EVENT_DESCRIPTIONS,
    EVENT_TYPES,
    VOCABULARY_VERSION,
    Part,
    UnknownEventTypeError,
    canonical_type,
    derive_part,
    reduce_parts,
    require_known_type,
)


class TestVocabulary:
    def test_is_versioned(self):
        assert isinstance(VOCABULARY_VERSION, int)
        assert VOCABULARY_VERSION >= 1

    def test_every_type_is_dotted_lowercase(self):
        import re

        for t in EVENT_TYPES:
            assert re.fullmatch(r"[a-z0-9_]+(\.[a-z0-9_]+)+", t), t

    def test_holds_the_timeline_types(self):
        assert {
            "turn.started",
            "turn.completed",
            "turn.aborted",
            "budget.warning",
            "budget.exceeded",
            "budget.updated",
            "service.payment",
            "service.budget_warning",
            "service.budget_exceeded",
            "context.compacted",
            "context.warning",
            "answer.checked",
            "model.changed",
            "model.fallback",
            "model.unavailable",
            "runtime.discovered",
            "command.received",
            "command.rejected",
            "delegation.started",
            "delegation.completed",
            "delegation.failed",
            "execution.continued_as_new",
            "execution.paused",
            "execution.resumed",
            "message.queued",
            "message.removed",
            "input.submitted",
        } <= EVENT_TYPES

    def test_holds_the_part_and_lifecycle_types(self):
        assert {
            "llm.call.started",
            "llm.call.completed",
            "llm.call.failed",
            "llm.call.chunk",
            "tool.call",
            "tool.result",
            "tool.progress",
            "approval.requested",
            "approval.decided",
            "input.request",
            "input.response",
            "task.started",
            "task.completed",
            "task.failed",
            "task.cancelled",
            "execution.finished",
        } <= EVENT_TYPES

    def test_known_type_passes(self):
        assert require_known_type("turn.started") == "turn.started"

    @pytest.mark.parametrize(
        "bare",
        ["IterationStarted", "BudgetWarning", "WorkflowCommandReceived", "MessageQueued", ""],
    )
    def test_bare_or_unknown_type_is_rejected(self, bare):
        with pytest.raises(UnknownEventTypeError):
            require_known_type(bare)

    def test_unknown_type_error_is_a_value_error(self):
        assert issubclass(UnknownEventTypeError, ValueError)

    def test_every_type_is_described(self):
        assert set(EVENT_DESCRIPTIONS) == EVENT_TYPES
        assert all(description.strip() for description in EVENT_DESCRIPTIONS.values())

    def test_webapp_mirror_holds_the_same_list_and_version(self):
        import re
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[4] / "agentarea-webapp/src/lib/events/contract.ts"
        ).read_text()
        block = re.search(r"export const EVENT_TYPES = \[(.*?)\] as const;", source, re.S)
        version = re.search(r"export const VOCABULARY_VERSION = (\d+);", source)
        assert block and version
        mirrored = re.findall(r'"([^"]+)"', block.group(1))
        assert len(mirrored) == len(set(mirrored))
        assert set(mirrored) == EVENT_TYPES
        assert int(version.group(1)) == VOCABULARY_VERSION


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
            "approval.requested",
            "approval.decided",
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
        assert canonical_type("budget.warning") == "budget.warning"
        assert canonical_type("turn.started") == "turn.started"

    def test_idempotent_for_known_inputs(self):
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
            "approval.requested",
            {"escalation_id": "esc-1", "tool_name": "shell"},
        )
        assert part is not None
        assert part.kind == "form"
        assert part.part_id == "esc-1"
        assert part.event_type == "approval.requested"

    def test_approval_response_supersedes(self):
        req = derive_part("approval.requested", {"escalation_id": "esc-3"})
        resp = derive_part("approval.decided", {"escalation_id": "esc-3"})
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
            (
                "llm.call.chunk",
                {"execution_id": "e", "iteration": 1, "chunk": "h", "chunk_index": 0},
            ),
            (
                "llm.call.chunk",
                {"execution_id": "e", "iteration": 1, "chunk": "i", "chunk_index": 1},
            ),
            ("llm.call.completed", {"execution_id": "e", "iteration": 1, "content": "hi"}),
        ]
        parts = reduce_parts(events)
        assert len(parts) == 1
        assert parts[0].event_type == "llm.call.completed"
        assert parts[0].part_id == "e:1"

    def test_compaction_call_never_merges_with_the_turn_reply(self):
        events = [
            (
                "llm.call.completed",
                {"execution_id": "e", "iteration": 3, "purpose": "compaction", "content": ""},
            ),
            ("llm.call.started", {"execution_id": "e", "iteration": 3}),
            ("llm.call.completed", {"execution_id": "e", "iteration": 3, "content": "answer"}),
        ]
        parts = reduce_parts(events)
        reply = next(p for p in parts if p.part_id == "e:3")
        assert reply.data["content"] == "answer"
        assert [p.part_id for p in parts] == ["e:3:compaction", "e:3"]

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
