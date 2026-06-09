"""Unit tests for WebhookManager integrations."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_triggers.domain.enums import WebhookType
from agentarea_triggers.domain.models import WebhookTrigger
from agentarea_triggers.webhook_manager import (
    DefaultWebhookManager,
    WebhookExecutionCallback,
    WebhookRequestData,
)


class MockWebhookExecutionCallback(WebhookExecutionCallback):
    """Mock webhook execution callback for testing."""
    def __init__(self):
        self.execute_webhook_trigger = AsyncMock()

    async def execute_webhook_trigger(self, webhook_id: str, request_data: dict):
        return await self.execute_webhook_trigger(webhook_id, request_data)

@pytest.fixture
def mock_execution_callback():
    """Create a mock webhook execution callback."""
    return MockWebhookExecutionCallback()

@pytest.fixture
def webhook_manager(mock_execution_callback):
    """Create a DefaultWebhookManager instance for testing."""
    return DefaultWebhookManager(
        execution_callback=mock_execution_callback, event_broker=None, base_url="/webhooks"
    )

@pytest.mark.asyncio
async def test_parse_linear_webhook(webhook_manager):
    """Test parsing Linear webhook data."""
    trigger = WebhookTrigger(
        id=uuid4(),
        name="Linear Trigger",
        description="Linear trigger",
        agent_id=uuid4(),
        webhook_id="linear_123",
        allowed_methods=["POST"],
        webhook_type=WebhookType.LINEAR,
        created_by="test_user",
        is_active=True,
    )

    linear_payload = {
        "action": "create",
        "type": "Issue",
        "createdAt": "2023-01-01T12:00:00Z",
        "data": {
            "id": "issue_123",
            "title": "Test Issue",
            "team": {"id": "team_123", "key": "TEST"},
        },
        "url": "https://linear.app/test/issue/TEST-123/test-issue",
    }

    request_data = WebhookRequestData(
        webhook_id="linear_123",
        method="POST",
        headers={"content-type": "application/json"},
        body=linear_payload,
        query_params={},
    )

    parsed_data = await webhook_manager._parse_webhook_data(trigger, request_data)

    assert parsed_data["webhook_type"] == "linear"
    assert parsed_data["linear_action"] == "create"
    assert parsed_data["linear_type"] == "Issue"
    assert parsed_data["linear_created_at"] == "2023-01-01T12:00:00Z"
    assert parsed_data["linear_data"]["id"] == "issue_123"
    assert parsed_data["linear_url"] == "https://linear.app/test/issue/TEST-123/test-issue"
    assert parsed_data["raw_data"] == linear_payload

@pytest.mark.asyncio
async def test_parse_discord_webhook(webhook_manager):
    """Test parsing Discord webhook data."""
    trigger = WebhookTrigger(
        id=uuid4(),
        name="Discord Trigger",
        description="Discord trigger",
        agent_id=uuid4(),
        webhook_id="discord_123",
        allowed_methods=["POST"],
        webhook_type=WebhookType.DISCORD,
        created_by="test_user",
        is_active=True,
    )

    discord_payload = {
        "channel_id": "channel_123",
        "guild_id": "guild_123",
        "author": {"username": "testuser"},
        "content": "Hello world",
    }

    request_data = WebhookRequestData(
        webhook_id="discord_123",
        method="POST",
        headers={"content-type": "application/json"},
        body=discord_payload,
        query_params={},
    )

    parsed_data = await webhook_manager._parse_webhook_data(trigger, request_data)

    assert parsed_data["webhook_type"] == "discord"
    assert parsed_data["discord_channel_id"] == "channel_123"
    assert parsed_data["discord_guild_id"] == "guild_123"
    assert parsed_data["discord_author"] == "testuser"
    assert parsed_data["discord_content"] == "Hello world"
    assert parsed_data["raw_data"] == discord_payload

@pytest.mark.asyncio
async def test_parse_github_webhook(webhook_manager):
    """Test parsing GitHub webhook data."""
    trigger = WebhookTrigger(
        id=uuid4(),
        name="GitHub Trigger",
        description="GitHub trigger",
        agent_id=uuid4(),
        webhook_id="github_123",
        allowed_methods=["POST"],
        webhook_type=WebhookType.GITHUB,
        created_by="test_user",
        is_active=True,
    )

    github_payload = {
        "action": "opened",
        "repository": {"full_name": "owner/repo"},
        "sender": {"login": "testuser"},
        "issue": {"number": 1, "title": "Test Issue"},
    }

    request_data = WebhookRequestData(
        webhook_id="github_123",
        method="POST",
        headers={
            "content-type": "application/json",
            "x-github-event": "issues",
            "x-github-delivery": "delivery_123",
        },
        body=github_payload,
        query_params={},
    )

    parsed_data = await webhook_manager._parse_webhook_data(trigger, request_data)

    assert parsed_data["webhook_type"] == "github"
    assert parsed_data["github_event"] == "issues"
    assert parsed_data["github_delivery"] == "delivery_123"
    assert parsed_data["repository"]["full_name"] == "owner/repo"
    assert parsed_data["sender"]["login"] == "testuser"
    assert parsed_data["action"] == "opened"
    assert parsed_data["raw_data"] == github_payload

@pytest.mark.asyncio
async def test_parse_slack_webhook(webhook_manager):
    """Test parsing Slack webhook data."""
    trigger = WebhookTrigger(
        id=uuid4(),
        name="Slack Trigger",
        description="Slack trigger",
        agent_id=uuid4(),
        webhook_id="slack_123",
        allowed_methods=["POST"],
        webhook_type=WebhookType.SLACK,
        created_by="test_user",
        is_active=True,
    )

    slack_payload = {
        "team_id": "T12345",
        "channel_id": "C12345",
        "user_id": "U12345",
        "text": "Hello Slack",
        "ts": "1234567890.123456",
    }

    request_data = WebhookRequestData(
        webhook_id="slack_123",
        method="POST",
        headers={"content-type": "application/json"},
        body=slack_payload,
        query_params={},
    )

    parsed_data = await webhook_manager._parse_webhook_data(trigger, request_data)

    assert parsed_data["webhook_type"] == "slack"
    assert parsed_data["team_id"] == "T12345"
    assert parsed_data["channel"] == "C12345"
    assert parsed_data["user"] == "U12345"
    assert parsed_data["text"] == "Hello Slack"
    assert parsed_data["ts"] == "1234567890.123456"
    assert parsed_data["raw_data"] == slack_payload
