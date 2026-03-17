"""Tests for RecallHistoryRequest/Result models."""

from uuid import UUID, uuid4

import pytest

from agentarea_execution.models import RecallHistoryRequest, RecallHistoryResult


class TestRecallHistoryRequest:
    def test_minimal_request(self):
        req = RecallHistoryRequest(
            task_id=uuid4(),
            workspace_id="ws-1",
        )
        assert req.query is None
        assert req.event_types is None
        assert req.limit == 20

    def test_full_request(self):
        task_id = uuid4()
        req = RecallHistoryRequest(
            task_id=task_id,
            workspace_id="ws-1",
            query="tool results",
            event_types=["ToolCallCompleted", "LLMCallCompleted"],
            limit=10,
            user_context_data={"org": "test"},
        )
        assert req.task_id == task_id
        assert req.query == "tool results"
        assert len(req.event_types) == 2
        assert req.limit == 10

    def test_serialization_roundtrip(self):
        req = RecallHistoryRequest(
            task_id=uuid4(),
            workspace_id="ws-1",
            event_types=["ToolCallCompleted"],
        )
        data = req.model_dump()
        restored = RecallHistoryRequest(**data)
        assert restored.task_id == req.task_id
        assert restored.event_types == ["ToolCallCompleted"]


class TestRecallHistoryResult:
    def test_empty_result(self):
        result = RecallHistoryResult()
        assert result.events == []
        assert result.total_count == 0
        assert result.summary == ""

    def test_with_events(self):
        events = [
            {"event_type": "ToolCallCompleted", "data": {"tool": "search"}, "created_at": "2026-03-11"},
            {"event_type": "LLMCallCompleted", "data": {"model": "gpt-4"}, "created_at": "2026-03-11"},
        ]
        result = RecallHistoryResult(
            events=events,
            total_count=2,
            summary="Retrieved 2 events: 1x ToolCallCompleted, 1x LLMCallCompleted",
        )
        assert len(result.events) == 2
        assert result.total_count == 2
        assert "ToolCallCompleted" in result.summary

    def test_error_result(self):
        result = RecallHistoryResult(
            summary="Failed to recall history: connection error",
        )
        assert result.total_count == 0
        assert "Failed" in result.summary
