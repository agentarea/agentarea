"""Integration tests for audit logging with workspace-scoped repository."""

import json
import logging
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest

from ..auth.context import UserContext
from ..base.models import WorkspaceScopedMixin
from ..base.workspace_scoped_repository import WorkspaceScopedRepository
from .audit_logger import get_audit_logger
from .config import setup_logging


class MockModel(WorkspaceScopedMixin):
    """Mock model for testing."""

    def __init__(self, **kwargs):
        self.id = kwargs.get("id", str(uuid4()))
        self.created_by = kwargs.get("created_by")
        self.workspace_id = kwargs.get("workspace_id")
        self.name = kwargs.get("name", "Test")

    @classmethod
    def __name__(cls):
        """Return the mock model name used in tests."""
        return "MockModel"


class TestAuditLoggingIntegration:
    """Test audit logging integration with repository."""

    @pytest.fixture
    def user_context(self):
        """User context fixture."""
        return UserContext(user_id="user123", workspace_id="workspace456")

    @pytest.fixture
    def mock_session(self):
        """Mock database session."""
        session = AsyncMock()
        session.add = Mock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()
        session.delete = AsyncMock()
        session.rollback = AsyncMock()
        return session

    @pytest.fixture
    def repository(self, mock_session, user_context):
        """Repository fixture."""
        return WorkspaceScopedRepository(mock_session, MockModel, user_context)

    def setup_method(self):
        """Setup logging for each test."""
        setup_logging(level="DEBUG", enable_audit_logging=True)

    @pytest.mark.asyncio
    async def test_create_logs_audit_event(self, repository, user_context):
        """Test that create operation logs audit event."""
        with patch("logging.getLogger") as mock_get_logger:
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger

            # Mock the model creation
            mock_model = MockModel(id="test123", name="Test Model")
            repository.session.add = Mock()
            repository.session.commit = AsyncMock()
            repository.session.refresh = AsyncMock()

            with patch.object(MockModel, "__call__", return_value=mock_model):
                result = await repository.create(name="Test Model")

            # Verify audit logging was called
            mock_logger.info.assert_called()
            call_args = mock_logger.info.call_args
            assert "AUDIT: CREATE" in call_args[0][0]
            assert call_args[1]["extra"]["action"] == "create"
            assert call_args[1]["extra"]["user_id"] == "user123"
            assert call_args[1]["extra"]["workspace_id"] == "workspace456"

    @pytest.mark.asyncio
    async def test_update_logs_audit_event(self, repository, user_context):
        """Test that update operation logs audit event."""
        with patch("logging.getLogger") as mock_get_logger:
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger

            # Mock finding the existing record
            mock_model = MockModel(id="test123", name="Original Name")
            mock_result = Mock()
            mock_result.scalar_one_or_none.return_value = mock_model
            repository.session.execute = AsyncMock(return_value=mock_result)
            repository.session.commit = AsyncMock()
            repository.session.refresh = AsyncMock()

            result = await repository.update("test123", name="Updated Name")

            # Verify audit logging was called
            mock_logger.info.assert_called()
            call_args = mock_logger.info.call_args
            assert "AUDIT: UPDATE" in call_args[0][0]
            assert call_args[1]["extra"]["action"] == "update"

    @pytest.mark.asyncio
    async def test_delete_logs_audit_event(self, repository, user_context):
        """Test that delete operation logs audit event."""
        with patch("logging.getLogger") as mock_get_logger:
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger

            # Mock finding the existing record
            mock_model = MockModel(id="test123", name="Test Model")
            mock_result = Mock()
            mock_result.scalar_one_or_none.return_value = mock_model
            repository.session.execute = AsyncMock(return_value=mock_result)
            repository.session.delete = AsyncMock()
            repository.session.commit = AsyncMock()

            result = await repository.delete("test123")

            # Verify audit logging was called
            mock_logger.info.assert_called()
            call_args = mock_logger.info.call_args
            assert "AUDIT: DELETE" in call_args[0][0]
            assert call_args[1]["extra"]["action"] == "delete"

    @pytest.mark.asyncio
    async def test_get_by_id_logs_read_event(self, repository, user_context):
        """Test that get_by_id operation logs read event."""
        with patch("logging.getLogger") as mock_get_logger:
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger

            # Mock finding the record
            mock_model = MockModel(id="test123", name="Test Model")
            mock_result = Mock()
            mock_result.scalar_one_or_none.return_value = mock_model
            repository.session.execute = AsyncMock(return_value=mock_result)

            result = await repository.get_by_id("test123")

            # Verify audit logging was called
            mock_logger.info.assert_called()
            call_args = mock_logger.info.call_args
            assert "AUDIT: READ" in call_args[0][0]
            assert call_args[1]["extra"]["action"] == "read"

    @pytest.mark.asyncio
    async def test_list_all_logs_list_event(self, repository, user_context):
        """Test that list_all operation logs list event."""
        with patch("logging.getLogger") as mock_get_logger:
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger

            # Mock finding records
            mock_models = [
                MockModel(id="test1", name="Model 1"),
                MockModel(id="test2", name="Model 2"),
            ]
            mock_result = Mock()
            mock_result.scalars.return_value.all.return_value = mock_models
            repository.session.execute = AsyncMock(return_value=mock_result)

            result = await repository.list_all()

            # Verify audit logging was called
            mock_logger.info.assert_called()
            call_args = mock_logger.info.call_args
            assert "AUDIT: LIST" in call_args[0][0]
            assert call_args[1]["extra"]["action"] == "list"

    @pytest.mark.asyncio
    async def test_error_logs_error_event(self, repository, user_context):
        """Test that errors log error events."""
        with patch("logging.getLogger") as mock_get_logger:
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger

            # Mock database error
            repository.session.execute = AsyncMock(side_effect=Exception("Database error"))

            with pytest.raises(Exception):
                await repository.get_by_id("test123")

            # Verify error logging was called
            mock_logger.info.assert_called()
            call_args = mock_logger.info.call_args
            assert "AUDIT: ERROR" in call_args[0][0]
            assert call_args[1]["extra"]["action"] == "error"

    def test_audit_log_contains_workspace_context(self, user_context):
        """Test that audit logs contain workspace context."""
        with patch("logging.getLogger") as mock_get_logger:
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger

            audit_logger = get_audit_logger()
            audit_logger.log_create(
                resource_type="test", user_context=user_context, resource_id="test123"
            )

            # Verify workspace context is included
            call_args = mock_logger.info.call_args
            extra = call_args[1]["extra"]
            assert extra["user_id"] == "user123"
            assert extra["workspace_id"] == "workspace456"
            assert extra["resource_type"] == "test"
            assert "audit_event" in extra

            audit_event = extra["audit_event"]
            assert audit_event["user_id"] == "user123"
            assert audit_event["workspace_id"] == "workspace456"
            assert audit_event["resource_id"] == "test123"

    def test_structured_logging_format(self, user_context):
        """Test that structured logging produces valid JSON."""
        from ..logging.config import WorkspaceContextFormatter

        formatter = WorkspaceContextFormatter()

        # Create a log record with audit event
        record = logging.LogRecord(
            name="agentarea.audit",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="AUDIT: CREATE test",
            args=(),
            exc_info=None,
        )

        # Add workspace context and audit event
        record.user_id = user_context.user_id
        record.workspace_id = user_context.workspace_id
        record.audit_event = {
            "action": "create",
            "resource_type": "test",
            "resource_id": "test123",
            "user_id": user_context.user_id,
            "workspace_id": user_context.workspace_id,
        }

        # Format the record
        formatted = formatter.format(record)

        # Verify it's valid JSON
        parsed = json.loads(formatted)
        assert parsed["user_id"] == "user123"
        assert parsed["workspace_id"] == "workspace456"
        assert parsed["audit_event"]["action"] == "create"
        assert parsed["audit_event"]["resource_type"] == "test"
