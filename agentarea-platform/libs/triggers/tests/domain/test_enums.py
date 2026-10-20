"""Tests for trigger enums."""

from agentarea_triggers.domain.enums import (
    ExecutionStatus,
    TriggerStatus,
    TriggerType,
)


class TestTriggerType:
    """Test TriggerType enum."""

    def test_trigger_type_values(self):
        """Test that TriggerType has expected values."""
        assert TriggerType.CRON == "cron"
        assert TriggerType.STREAM == "stream"

    def test_trigger_type_membership(self):
        """Test TriggerType membership."""
        assert "cron" in TriggerType
        assert "stream" in TriggerType
        assert "webhook" not in TriggerType
        assert "invalid" not in TriggerType

    def test_trigger_type_iteration(self):
        """Test TriggerType iteration."""
        types = list(TriggerType)
        assert types == [TriggerType.CRON, TriggerType.STREAM]


class TestTriggerStatus:
    """Test TriggerStatus enum."""

    def test_trigger_status_values(self):
        """Test that TriggerStatus has expected values."""
        assert TriggerStatus.ACTIVE == "active"
        assert TriggerStatus.INACTIVE == "inactive"
        assert TriggerStatus.DISABLED == "disabled"
        assert TriggerStatus.FAILED == "failed"

    def test_trigger_status_membership(self):
        """Test TriggerStatus membership."""
        assert "active" in TriggerStatus
        assert "inactive" in TriggerStatus
        assert "disabled" in TriggerStatus
        assert "failed" in TriggerStatus
        assert "invalid" not in TriggerStatus


class TestExecutionStatus:
    """Test ExecutionStatus enum."""

    def test_execution_status_values(self):
        """Test that ExecutionStatus has expected values."""
        assert ExecutionStatus.SUCCESS == "success"
        assert ExecutionStatus.FAILED == "failed"
        assert ExecutionStatus.TIMEOUT == "timeout"
        assert ExecutionStatus.CANCELLED == "cancelled"

    def test_execution_status_membership(self):
        """Test ExecutionStatus membership."""
        assert "success" in ExecutionStatus
        assert "failed" in ExecutionStatus
        assert "timeout" in ExecutionStatus
        assert "cancelled" in ExecutionStatus
        assert "invalid" not in ExecutionStatus
