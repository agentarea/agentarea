"""Tests for trigger enums."""

from agentarea_triggers.domain.enums import (
    ExecutionStatus,
    TriggerStatus,
    TriggerType,
    WebhookType,
)


class TestTriggerType:
    """Test TriggerType enum."""

    def test_trigger_type_values(self):
        """Test that TriggerType has expected values."""
        assert TriggerType.CRON == "cron"
        assert TriggerType.WEBHOOK == "webhook"

    def test_trigger_type_membership(self):
        """Test TriggerType membership."""
        assert "cron" in TriggerType
        assert "webhook" in TriggerType
        assert "invalid" not in TriggerType

    def test_trigger_type_iteration(self):
        """Test TriggerType iteration."""
        types = list(TriggerType)
        assert len(types) == 3
        assert TriggerType.CRON in types
        assert TriggerType.WEBHOOK in types


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


class TestWebhookType:
    """Test WebhookType enum."""

    def test_webhook_type_values(self):
        """Test that WebhookType has expected values."""
        assert WebhookType.GENERIC == "generic"
        assert WebhookType.TELEGRAM == "telegram"
        assert WebhookType.SLACK == "slack"
        assert WebhookType.GITHUB == "github"
        assert WebhookType.DISCORD == "discord"
        assert WebhookType.STRIPE == "stripe"

    def test_webhook_type_membership(self):
        """Known values resolve to the declared members.

        Deliberately does not use ``x in WebhookType``. Unlike the other enums
        here, WebhookType defines ``_missing_`` so a webhook type can be
        configured dynamically, and CPython changed what ``__contains__`` does for
        such an enum between 3.12.9 and 3.12.14: the same expression is False on
        one and True on the other. Asserting on it tests the interpreter, not the
        contract — which is why this passed locally and failed in CI.
        """
        for value in ("generic", "telegram", "slack", "github", "discord", "stripe"):
            assert WebhookType(value).value == value

    def test_webhook_type_accepts_unknown_values(self):
        """Unknown strings are accepted rather than rejected — that is the design.

        ``_missing_`` exists so pydantic takes any string for a webhook type. The
        pass-through value must still behave as the string it came from, and must
        not leak into the declared member list.
        """
        custom = WebhookType("some-dynamic-provider")

        assert custom == "some-dynamic-provider"
        assert isinstance(custom, str)
        assert custom not in list(WebhookType)
        assert len(list(WebhookType)) == 9

    def test_webhook_type_iteration(self):
        """Test WebhookType iteration."""
        types = list(WebhookType)
        assert len(types) == 9
        assert WebhookType.GENERIC in types
        assert WebhookType.TELEGRAM in types
