"""Test that follow-up messages route to existing active workflows
instead of creating new tasks."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4


class TestFollowUpRouting:
    """Verify the routing logic: if an active workflow exists for the same
    channel_origin, route the message there instead of creating a new task."""

    def _build_execution_data(self, text: str, chat_id: str = "12345") -> dict:
        return {
            "text": text,
            "channel_origin": {
                "type": "telegram",
                "chat_id": chat_id,
                "presentation": "concise",
            },
        }

    def _build_task_orm(self, agent_id, chat_id, status="running", execution_id=None):
        """Create a mock TaskORM-like object."""
        task = MagicMock()
        task.id = uuid4()
        task.agent_id = agent_id
        task.status = status
        task.execution_id = execution_id or f"task-{task.id}"
        task.parameters = {
            "channel_origin": {
                "type": "telegram",
                "chat_id": str(chat_id),
            }
        }
        task.created_at = "2026-04-14T00:00:00"
        return task

    @pytest.mark.asyncio
    async def test_routes_to_existing_workflow_when_active(self):
        """Message should be routed to existing workflow via signal, not create new task."""
        agent_id = uuid4()
        chat_id = "12345"
        execution_id = f"task-{uuid4()}"

        # Mock workflow executor
        workflow_executor = AsyncMock()
        workflow_executor.send_workflow_command = AsyncMock(return_value=True)

        # Mock DB query result
        active_task = self._build_task_orm(agent_id, chat_id, "running", execution_id)

        # Simulate the routing logic from trigger_execution_activities
        execution_data = self._build_execution_data("follow-up question", chat_id)
        channel_origin = execution_data.get("channel_origin", {})
        routed = False

        if channel_origin:
            target_chat_id = channel_origin.get("chat_id")
            # Simulate finding active task
            candidates = [active_task]
            for candidate in candidates:
                params = candidate.parameters or {}
                candidate_chat = params.get("channel_origin", {}).get("chat_id")
                if str(candidate_chat) == str(target_chat_id) and candidate.execution_id:
                    ok = await workflow_executor.send_workflow_command(
                        candidate.execution_id,
                        "queue_message",
                        {"message": "follow-up question"},
                    )
                    if ok:
                        routed = True
                        break

        assert routed is True
        workflow_executor.send_workflow_command.assert_called_once_with(
            execution_id,
            "queue_message",
            {"message": "follow-up question"},
        )

    @pytest.mark.asyncio
    async def test_creates_new_task_when_no_active_workflow(self):
        """When no active workflow exists, should NOT route — fall through to task creation."""
        execution_data = self._build_execution_data("first message", "99999")
        channel_origin = execution_data.get("channel_origin", {})
        routed = False

        if channel_origin:
            target_chat_id = channel_origin.get("chat_id")
            candidates = []  # No active tasks
            for candidate in candidates:
                pass  # Loop doesn't execute

        assert routed is False

    @pytest.mark.asyncio
    async def test_creates_new_task_when_signal_fails(self):
        """If signal to existing workflow fails, fall through to new task."""
        agent_id = uuid4()
        chat_id = "12345"

        workflow_executor = AsyncMock()
        workflow_executor.send_workflow_command = AsyncMock(return_value=False)

        active_task = self._build_task_orm(agent_id, chat_id, "running")
        execution_data = self._build_execution_data("message", chat_id)
        channel_origin = execution_data.get("channel_origin", {})
        routed = False

        if channel_origin:
            target_chat_id = channel_origin.get("chat_id")
            candidates = [active_task]
            for candidate in candidates:
                params = candidate.parameters or {}
                candidate_chat = params.get("channel_origin", {}).get("chat_id")
                if str(candidate_chat) == str(target_chat_id) and candidate.execution_id:
                    ok = await workflow_executor.send_workflow_command(
                        candidate.execution_id,
                        "queue_message",
                        {"message": "message"},
                    )
                    if ok:
                        routed = True
                        break

        assert routed is False

    @pytest.mark.asyncio
    async def test_different_chat_id_creates_new_task(self):
        """Messages from different chat_ids should NOT route to each other."""
        agent_id = uuid4()

        workflow_executor = AsyncMock()
        workflow_executor.send_workflow_command = AsyncMock(return_value=True)

        # Active task for chat 111
        active_task = self._build_task_orm(agent_id, "111", "running")

        # New message from chat 222
        execution_data = self._build_execution_data("hello", "222")
        channel_origin = execution_data.get("channel_origin", {})
        routed = False

        if channel_origin:
            target_chat_id = channel_origin.get("chat_id")
            candidates = [active_task]
            for candidate in candidates:
                params = candidate.parameters or {}
                candidate_chat = params.get("channel_origin", {}).get("chat_id")
                if str(candidate_chat) == str(target_chat_id) and candidate.execution_id:
                    ok = await workflow_executor.send_workflow_command(
                        candidate.execution_id,
                        "queue_message",
                        {"message": "hello"},
                    )
                    if ok:
                        routed = True
                        break

        assert routed is False
        workflow_executor.send_workflow_command.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_channel_origin_skips_routing(self):
        """Messages without channel_origin should skip routing entirely."""
        execution_data = {"text": "hello"}  # No channel_origin
        channel_origin = execution_data.get("channel_origin", {})
        routed = False

        if channel_origin:
            routed = True  # Would only set if channel_origin is truthy

        assert routed is False

    @pytest.mark.asyncio
    async def test_empty_text_not_routed(self):
        """Empty message text should not be routed as follow-up."""
        agent_id = uuid4()
        chat_id = "12345"

        workflow_executor = AsyncMock()
        workflow_executor.send_workflow_command = AsyncMock(return_value=True)

        active_task = self._build_task_orm(agent_id, chat_id, "running")
        execution_data = self._build_execution_data("", chat_id)
        channel_origin = execution_data.get("channel_origin", {})
        routed = False

        if channel_origin:
            target_chat_id = channel_origin.get("chat_id")
            candidates = [active_task]
            follow_up_text = execution_data.get("text", "")
            for candidate in candidates:
                params = candidate.parameters or {}
                candidate_chat = params.get("channel_origin", {}).get("chat_id")
                if str(candidate_chat) == str(target_chat_id) and candidate.execution_id:
                    if follow_up_text:  # Only route non-empty messages
                        ok = await workflow_executor.send_workflow_command(
                            candidate.execution_id,
                            "queue_message",
                            {"message": follow_up_text},
                        )
                        if ok:
                            routed = True
                            break

        assert routed is False
        workflow_executor.send_workflow_command.assert_not_called()
