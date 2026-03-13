"""Tests for the auto_heartbeater decorator."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentarea_execution.activities.heartbeat import auto_heartbeater


class TestAutoHeartbeater:
    """Tests for the auto_heartbeater decorator."""

    @pytest.fixture
    def mock_activity_info(self):
        """Create a mock activity info with heartbeat_timeout."""
        info = MagicMock()
        info.heartbeat_timeout = MagicMock()
        info.heartbeat_timeout.total_seconds.return_value = 30.0
        return info

    @pytest.fixture
    def mock_activity_info_no_timeout(self):
        """Create a mock activity info without heartbeat_timeout."""
        info = MagicMock()
        info.heartbeat_timeout = None
        return info

    @pytest.mark.asyncio
    async def test_decorated_function_returns_result(self, mock_activity_info):
        """The decorated function should return the original result."""

        @auto_heartbeater
        async def my_activity():
            return "result"

        with patch("agentarea_execution.activities.heartbeat.activity") as mock_act:
            mock_act.info.return_value = mock_activity_info
            mock_act.heartbeat = MagicMock()
            result = await my_activity()

        assert result == "result"

    @pytest.mark.asyncio
    async def test_heartbeat_called_when_timeout_set(self, mock_activity_info):
        """Heartbeat should be called at least once for a slow activity."""

        @auto_heartbeater
        async def slow_activity():
            await asyncio.sleep(0.1)
            return "done"

        with patch("agentarea_execution.activities.heartbeat.activity") as mock_act:
            # Set heartbeat interval to 0.02s (timeout=0.04s / 2)
            mock_activity_info.heartbeat_timeout.total_seconds.return_value = 0.04
            mock_act.info.return_value = mock_activity_info
            mock_act.heartbeat = MagicMock()
            result = await slow_activity()

        assert result == "done"
        assert mock_act.heartbeat.call_count >= 1

    @pytest.mark.asyncio
    async def test_no_heartbeat_when_no_timeout(self, mock_activity_info_no_timeout):
        """No heartbeat task when heartbeat_timeout is None."""

        @auto_heartbeater
        async def my_activity():
            return "result"

        with patch("agentarea_execution.activities.heartbeat.activity") as mock_act:
            mock_act.info.return_value = mock_activity_info_no_timeout
            mock_act.heartbeat = MagicMock()
            result = await my_activity()

        assert result == "result"
        mock_act.heartbeat.assert_not_called()

    @pytest.mark.asyncio
    async def test_heartbeat_cancelled_on_exception(self, mock_activity_info):
        """Heartbeat task should be cancelled even if the activity raises."""

        @auto_heartbeater
        async def failing_activity():
            raise ValueError("boom")

        with patch("agentarea_execution.activities.heartbeat.activity") as mock_act:
            mock_act.info.return_value = mock_activity_info
            mock_act.heartbeat = MagicMock()

            with pytest.raises(ValueError, match="boom"):
                await failing_activity()

    @pytest.mark.asyncio
    async def test_preserves_function_name(self):
        """Decorator should preserve the original function name."""

        @auto_heartbeater
        async def my_named_activity():
            return True

        assert my_named_activity.__name__ == "my_named_activity"
