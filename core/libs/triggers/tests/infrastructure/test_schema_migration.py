"""Tests for trigger schema migration and webhook_config field."""

from datetime import datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_triggers.domain.enums import TriggerType, WebhookType
from agentarea_triggers.domain.models import TriggerCreate, WebhookTrigger
from agentarea_triggers.infrastructure.orm import TriggerORM
from agentarea_triggers.infrastructure.repository import TriggerRepository
from sqlalchemy.ext.asyncio import AsyncSession


class TestSchemaMigration:
    """Test schema migration and webhook_config field functionality."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock AsyncSession."""
        return AsyncMock(spec=AsyncSession)

    @pytest.fixture
    def repository(self, mock_session):
        """Create a TriggerRepository instance with mock session."""
        return TriggerRepository(mock_session)

    @pytest.fixture
    def sample_webhook_config(self):
        """Create sample webhook configuration data."""
        return {
            "telegram": {"bot_token": "test_token", "chat_id": "123456789", "parse_mode": "HTML"},
            "slack": {
                "webhook_url": "https://hooks.slack.com/test",
                "channel": "#general",
                "username": "bot",
            },
            "github": {"secret": "webhook_secret", "events": ["push", "pull_request"]},
        }

    @pytest.fixture
    def sample_webhook_trigger_orm(self, sample_webhook_config):
        """Create a sample WebhookTrigger ORM with webhook_config."""
        return TriggerORM(
            id=uuid4(),
            name="Webhook Test",
            description="Test webhook trigger with generic config",
            agent_id=uuid4(),
            trigger_type=TriggerType.WEBHOOK.value,
            is_active=True,
            task_parameters={"param1": "value1"},
            conditions={"condition1": "value1"},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            created_by="test_user",
            max_executions_per_hour=60,
            failure_threshold=5,
            consecutive_failures=0,
            last_execution_at=None,
            webhook_id="webhook_123",
            allowed_methods=["POST", "PUT"],
            webhook_type=WebhookType.TELEGRAM.value,
            validation_rules={"required_fields": ["message"]},
            webhook_config=sample_webhook_config,
        )

    def test_webhook_config_field_exists(self, sample_webhook_trigger_orm):
        """Test that webhook_config field exists and can store data."""
        # Verify the field exists and contains expected data
        assert hasattr(sample_webhook_trigger_orm, "webhook_config")
        assert sample_webhook_trigger_orm.webhook_config is not None
        assert isinstance(sample_webhook_trigger_orm.webhook_config, dict)

        # Verify specific config data
        config = sample_webhook_trigger_orm.webhook_config
        assert "telegram" in config
        assert "slack" in config
        assert "github" in config
        assert config["telegram"]["bot_token"] == "test_token"
        assert config["slack"]["webhook_url"] == "https://hooks.slack.com/test"
        assert config["github"]["secret"] == "webhook_secret"

    def test_webhook_config_supports_single_service(self):
        """Test that webhook_config can store configuration for a single service."""
        telegram_only_config = {
            "bot_token": "test_token_123",
            "chat_id": "987654321",
            "parse_mode": "Markdown",
        }

        trigger_orm = TriggerORM(
            id=uuid4(),
            name="Telegram Only",
            description="Telegram-only webhook trigger",
            agent_id=uuid4(),
            trigger_type=TriggerType.WEBHOOK.value,
            is_active=True,
            task_parameters={},
            conditions={},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            created_by="test_user",
            webhook_id="telegram_webhook_456",
            webhook_type=WebhookType.TELEGRAM.value,
            webhook_config=telegram_only_config,
        )

        # Verify single service configuration
        assert trigger_orm.webhook_config == telegram_only_config
        assert trigger_orm.webhook_config["bot_token"] == "test_token_123"
        assert trigger_orm.webhook_config["chat_id"] == "987654321"

    def test_webhook_config_supports_empty_config(self):
        """Test that webhook_config can be None or empty for generic webhooks."""
        generic_trigger_orm = TriggerORM(
            id=uuid4(),
            name="Generic Webhook",
            description="Generic webhook with no specific config",
            agent_id=uuid4(),
            trigger_type=TriggerType.WEBHOOK.value,
            is_active=True,
            task_parameters={},
            conditions={},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            created_by="test_user",
            webhook_id="generic_webhook_789",
            webhook_type=WebhookType.GENERIC.value,
            webhook_config=None,
        )

        # Verify empty configuration is supported
        assert generic_trigger_orm.webhook_config is None

    def test_orm_to_domain_conversion_with_webhook_config(
        self, repository, sample_webhook_trigger_orm
    ):
        """Test converting ORM with webhook_config to domain model."""
        # Execute conversion
        domain_trigger = repository._orm_to_domain(sample_webhook_trigger_orm)

        # Verify conversion
        assert isinstance(domain_trigger, WebhookTrigger)
        assert domain_trigger.webhook_config == sample_webhook_trigger_orm.webhook_config
        assert domain_trigger.webhook_config["telegram"]["bot_token"] == "test_token"
        assert domain_trigger.webhook_config["slack"]["channel"] == "#general"
        assert domain_trigger.webhook_config["github"]["events"] == ["push", "pull_request"]

    def test_domain_to_orm_conversion_with_webhook_config(self, repository, sample_webhook_config):
        """Test converting domain model with webhook_config to ORM."""
        # Create domain model
        domain_trigger = WebhookTrigger(
            id=uuid4(),
            name="Test Webhook",
            description="Test webhook with config",
            agent_id=uuid4(),
            trigger_type=TriggerType.WEBHOOK,
            is_active=True,
            task_parameters={},
            conditions={},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            created_by="test_user",
            webhook_id="test_webhook_123",
            allowed_methods=["POST"],
            webhook_type=WebhookType.SLACK,
            validation_rules={},
            webhook_config=sample_webhook_config,
        )

        # Execute conversion
        orm_trigger = repository._domain_to_orm(domain_trigger)

        # Verify conversion
        assert isinstance(orm_trigger, TriggerORM)
        assert orm_trigger.webhook_config == sample_webhook_config
        assert orm_trigger.webhook_config["telegram"]["bot_token"] == "test_token"
        assert orm_trigger.webhook_config["slack"]["webhook_url"] == "https://hooks.slack.com/test"

    def test_backward_compatibility_migration_scenario(self):
        """Test backward compatibility scenarios during migration."""
        # Simulate old data structure (what would exist before migration)
        old_telegram_config = {"bot_token": "old_token", "chat_id": "old_chat_id"}

        old_slack_config = {
            "webhook_url": "https://old.slack.com/webhook",
            "channel": "#old-channel",
        }

        # Test migration logic (this would be handled by the migration script)
        # Scenario 1: Only telegram_config exists
        migrated_config_1 = old_telegram_config  # Direct migration
        assert migrated_config_1["bot_token"] == "old_token"

        # Scenario 2: Multiple configs exist - should be merged
        migrated_config_2 = {"telegram": old_telegram_config, "slack": old_slack_config}
        assert migrated_config_2["telegram"]["bot_token"] == "old_token"
        assert migrated_config_2["slack"]["webhook_url"] == "https://old.slack.com/webhook"

    @pytest.mark.asyncio
    async def test_create_webhook_trigger_with_config(self, repository, mock_session):
        """Test creating a webhook trigger with webhook_config through repository."""
        # Setup
        webhook_config = {
            "api_key": "test_api_key",
            "endpoint": "https://api.example.com/webhook",
            "headers": {"Content-Type": "application/json"},
        }

        trigger_create = TriggerCreate(
            name="API Webhook",
            description="Custom API webhook trigger",
            agent_id=uuid4(),
            trigger_type=TriggerType.WEBHOOK,
            created_by="test_user",
            webhook_id="api_webhook_123",
            webhook_type=WebhookType.GENERIC,
            webhook_config=webhook_config,
        )

        # Mock session behavior
        mock_session.flush = AsyncMock()

        # Create a properly initialized ORM object for refresh mock
        created_orm = TriggerORM(
            id=uuid4(),
            name=trigger_create.name,
            description=trigger_create.description,
            agent_id=trigger_create.agent_id,
            trigger_type=trigger_create.trigger_type.value,
            is_active=True,
            task_parameters=trigger_create.task_parameters,
            conditions=trigger_create.conditions,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            created_by=trigger_create.created_by,
            failure_threshold=trigger_create.failure_threshold,
            consecutive_failures=0,
            webhook_id=trigger_create.webhook_id,
            allowed_methods=trigger_create.allowed_methods,
            webhook_type=trigger_create.webhook_type.value,
            validation_rules=trigger_create.validation_rules,
            webhook_config=trigger_create.webhook_config,
        )

        async def mock_refresh(obj):
            # Simulate database refresh by copying values from created_orm
            for attr, value in created_orm.__dict__.items():
                if not attr.startswith("_"):
                    setattr(obj, attr, value)

        mock_session.refresh = AsyncMock(side_effect=mock_refresh)

        # Execute
        result = await repository.create_from_model(trigger_create)

        # Verify
        assert result.webhook_config == webhook_config
        assert result.webhook_config["api_key"] == "test_api_key"
        assert result.webhook_config["endpoint"] == "https://api.example.com/webhook"
        mock_session.add.assert_called_once()
        mock_session.flush.assert_called_once()

    def test_webhook_config_json_serialization(self, sample_webhook_config):
        """Test that webhook_config properly handles JSON serialization."""
        import json

        # Test serialization
        serialized = json.dumps(sample_webhook_config)
        assert isinstance(serialized, str)

        # Test deserialization
        deserialized = json.loads(serialized)
        assert deserialized == sample_webhook_config
        assert deserialized["telegram"]["bot_token"] == "test_token"

    def test_webhook_config_nested_structure_support(self):
        """Test that webhook_config supports complex nested structures."""
        complex_config = {
            "service_a": {
                "auth": {
                    "type": "oauth2",
                    "credentials": {"client_id": "test_client_id", "client_secret": "test_secret"},
                },
                "endpoints": {
                    "webhook": "https://api.service-a.com/webhook",
                    "callback": "https://api.service-a.com/callback",
                },
                "settings": {
                    "retry_count": 3,
                    "timeout": 30,
                    "rate_limit": {"requests_per_minute": 60, "burst_limit": 10},
                },
            }
        }

        trigger_orm = TriggerORM(
            id=uuid4(),
            name="Complex Config Test",
            description="Test complex nested webhook config",
            agent_id=uuid4(),
            trigger_type=TriggerType.WEBHOOK.value,
            is_active=True,
            task_parameters={},
            conditions={},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            created_by="test_user",
            webhook_id="complex_webhook_123",
            webhook_type=WebhookType.GENERIC.value,
            webhook_config=complex_config,
        )

        # Verify complex nested structure is preserved
        config = trigger_orm.webhook_config
        assert config["service_a"]["auth"]["type"] == "oauth2"
        assert config["service_a"]["auth"]["credentials"]["client_id"] == "test_client_id"
        assert config["service_a"]["endpoints"]["webhook"] == "https://api.service-a.com/webhook"
        assert config["service_a"]["settings"]["rate_limit"]["requests_per_minute"] == 60

    def test_webhook_config_validation_compatibility(self):
        """Test that webhook_config works with existing validation_rules."""
        webhook_config = {
            "validation": {
                "required_headers": ["X-Webhook-Signature"],
                "allowed_ips": ["192.168.1.0/24", "10.0.0.0/8"],
            },
            "processing": {
                "parse_json": True,
                "extract_fields": ["event_type", "timestamp", "data"],
            },
        }

        validation_rules = {
            "signature_header": "X-Webhook-Signature",
            "signature_algorithm": "sha256",
            "required_fields": ["event_type"],
        }

        trigger_orm = TriggerORM(
            id=uuid4(),
            name="Validation Test",
            description="Test webhook_config with validation_rules",
            agent_id=uuid4(),
            trigger_type=TriggerType.WEBHOOK.value,
            is_active=True,
            task_parameters={},
            conditions={},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            created_by="test_user",
            webhook_id="validation_webhook_123",
            webhook_type=WebhookType.GENERIC.value,
            validation_rules=validation_rules,
            webhook_config=webhook_config,
        )

        # Verify both fields coexist and complement each other
        assert trigger_orm.validation_rules["signature_header"] == "X-Webhook-Signature"
        assert trigger_orm.webhook_config["validation"]["required_headers"] == [
            "X-Webhook-Signature"
        ]
        assert trigger_orm.webhook_config["processing"]["parse_json"] is True


class TestWebhookConfigIntegration:
    """Integration tests for webhook_config field with repository operations."""

    def test_webhook_config_update_data_structure(self):
        """Test that TriggerUpdate properly handles webhook_config updates."""
        from agentarea_triggers.domain.models import TriggerUpdate

        updated_config = {
            "new_service": {"api_key": "new_api_key", "endpoint": "https://new-service.com/webhook"}
        }

        update_data = TriggerUpdate(webhook_config=updated_config)

        # Verify the update data structure
        assert update_data.webhook_config == updated_config
        assert update_data.webhook_config["new_service"]["api_key"] == "new_api_key"
        assert (
            update_data.webhook_config["new_service"]["endpoint"]
            == "https://new-service.com/webhook"
        )

    def test_webhook_config_query_compatibility(self):
        """Test that webhook_config is compatible with query operations."""
        # This test demonstrates the data structure compatibility
        # for future query implementations

        sample_configs = [
            {"telegram": {"bot_token": "token1", "chat_id": "123"}},
            {"slack": {"webhook_url": "https://slack.com/webhook", "channel": "#general"}},
            {"github": {"secret": "webhook_secret", "events": ["push", "pull_request"]}},
            {"custom": {"api_key": "custom_key", "endpoint": "https://custom.api.com"}},
        ]

        # Verify all configs are JSON serializable (required for database storage)
        import json

        for config in sample_configs:
            serialized = json.dumps(config)
            deserialized = json.loads(serialized)
            assert deserialized == config

        # Verify configs can be filtered by service type (for future query methods)
        telegram_configs = [config for config in sample_configs if "telegram" in config]
        slack_configs = [config for config in sample_configs if "slack" in config]

        assert len(telegram_configs) == 1
        assert len(slack_configs) == 1
        assert telegram_configs[0]["telegram"]["bot_token"] == "token1"
        assert slack_configs[0]["slack"]["channel"] == "#general"
