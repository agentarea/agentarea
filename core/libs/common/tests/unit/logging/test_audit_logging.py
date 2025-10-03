"""Tests for audit logging with workspace context."""

import json
import logging
import tempfile
from unittest.mock import Mock, patch

from ..auth.context import UserContext
from .audit_logger import AuditAction, AuditEvent, AuditLogger, get_audit_logger
from .config import WorkspaceContextFormatter
from .context_logger import ContextLogger, get_context_logger
from .filters import WorkspaceContextFilter
from .query import AuditLogQuery


class TestAuditEvent:
    """Test AuditEvent class."""

    def test_create_audit_event(self):
        """Test creating an audit event."""
        user_context = UserContext(user_id="user123", workspace_id="workspace456")

        event = AuditEvent(
            action=AuditAction.CREATE,
            resource_type="agent",
            user_context=user_context,
            resource_id="agent123",
            resource_data={"name": "Test Agent"},
            additional_context={"source": "api"},
        )

        assert event.action == AuditAction.CREATE
        assert event.resource_type == "agent"
        assert event.user_id == "user123"
        assert event.workspace_id == "workspace456"
        assert event.resource_id == "agent123"
        assert event.resource_data == {"name": "Test Agent"}
        assert event.additional_context == {"source": "api"}
        assert event.error is None

    def test_audit_event_to_dict(self):
        """Test converting audit event to dictionary."""
        user_context = UserContext(user_id="user123", workspace_id="workspace456")

        event = AuditEvent(
            action=AuditAction.UPDATE,
            resource_type="task",
            user_context=user_context,
            resource_id="task123",
            error="Something went wrong",
        )

        event_dict = event.to_dict()

        assert event_dict["action"] == "update"
        assert event_dict["resource_type"] == "task"
        assert event_dict["user_id"] == "user123"
        assert event_dict["workspace_id"] == "workspace456"
        assert event_dict["resource_id"] == "task123"
        assert event_dict["error"] == "Something went wrong"
        assert "timestamp" in event_dict

    def test_audit_event_to_json(self):
        """Test converting audit event to JSON."""
        user_context = UserContext(user_id="user123", workspace_id="workspace456")

        event = AuditEvent(
            action=AuditAction.DELETE,
            resource_type="trigger",
            user_context=user_context,
            resource_id="trigger123",
        )

        json_str = event.to_json()
        parsed = json.loads(json_str)

        assert parsed["action"] == "delete"
        assert parsed["resource_type"] == "trigger"
        assert parsed["user_id"] == "user123"
        assert parsed["workspace_id"] == "workspace456"


class TestAuditLogger:
    """Test AuditLogger class."""

    def test_audit_logger_initialization(self):
        """Test audit logger initialization."""
        logger = AuditLogger("test.audit")
        assert logger.logger.name == "test.audit"

    def test_log_create(self):
        """Test logging create events."""
        user_context = UserContext(user_id="user123", workspace_id="workspace456")

        with patch("logging.getLogger") as mock_get_logger:
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger

            audit_logger = AuditLogger("test.audit")
            audit_logger.log_create(
                resource_type="agent",
                user_context=user_context,
                resource_id="agent123",
                resource_data={"name": "Test Agent"},
            )

            mock_logger.info.assert_called_once()
            call_args = mock_logger.info.call_args
            assert "AUDIT: CREATE agent" in call_args[0][0]
            assert call_args[1]["extra"]["action"] == "create"
            assert call_args[1]["extra"]["user_id"] == "user123"
            assert call_args[1]["extra"]["workspace_id"] == "workspace456"

    def test_log_update(self):
        """Test logging update events."""
        user_context = UserContext(user_id="user123", workspace_id="workspace456")

        with patch("logging.getLogger") as mock_get_logger:
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger

            audit_logger = AuditLogger("test.audit")
            audit_logger.log_update(
                resource_type="task",
                user_context=user_context,
                resource_id="task123",
                resource_data={"status": "completed"},
            )

            mock_logger.info.assert_called_once()
            call_args = mock_logger.info.call_args
            assert "AUDIT: UPDATE task" in call_args[0][0]
            assert call_args[1]["extra"]["action"] == "update"

    def test_log_delete(self):
        """Test logging delete events."""
        user_context = UserContext(user_id="user123", workspace_id="workspace456")

        with patch("logging.getLogger") as mock_get_logger:
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger

            audit_logger = AuditLogger("test.audit")
            audit_logger.log_delete(
                resource_type="trigger", user_context=user_context, resource_id="trigger123"
            )

            mock_logger.info.assert_called_once()
            call_args = mock_logger.info.call_args
            assert "AUDIT: DELETE trigger" in call_args[0][0]
            assert call_args[1]["extra"]["action"] == "delete"

    def test_log_error(self):
        """Test logging error events."""
        user_context = UserContext(user_id="user123", workspace_id="workspace456")

        with patch("logging.getLogger") as mock_get_logger:
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger

            audit_logger = AuditLogger("test.audit")
            audit_logger.log_error(
                resource_type="agent",
                user_context=user_context,
                error="Database connection failed",
                resource_id="agent123",
            )

            mock_logger.info.assert_called_once()
            call_args = mock_logger.info.call_args
            assert "AUDIT: ERROR agent" in call_args[0][0]
            assert call_args[1]["extra"]["action"] == "error"

    def test_get_audit_logger_singleton(self):
        """Test that get_audit_logger returns singleton."""
        logger1 = get_audit_logger()
        logger2 = get_audit_logger()
        assert logger1 is logger2


class TestContextLogger:
    """Test ContextLogger class."""

    def test_context_logger_with_context(self):
        """Test context logger with user context."""
        user_context = UserContext(user_id="user123", workspace_id="workspace456")

        mock_logger = Mock()
        context_logger = ContextLogger(mock_logger, user_context)

        context_logger.info("Test message")

        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args
        assert call_args[0][0] == "Test message"
        assert call_args[1]["extra"]["user_id"] == "user123"
        assert call_args[1]["extra"]["workspace_id"] == "workspace456"

    def test_context_logger_without_context(self):
        """Test context logger without user context."""
        mock_logger = Mock()
        context_logger = ContextLogger(mock_logger)

        context_logger.info("Test message")

        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args
        assert call_args[0][0] == "Test message"
        assert "user_id" not in call_args[1]["extra"]
        assert "workspace_id" not in call_args[1]["extra"]

    def test_context_logger_set_context(self):
        """Test setting context on context logger."""
        user_context = UserContext(user_id="user123", workspace_id="workspace456")

        mock_logger = Mock()
        context_logger = ContextLogger(mock_logger)
        context_logger.set_context(user_context)

        context_logger.info("Test message")

        call_args = mock_logger.info.call_args
        assert call_args[1]["extra"]["user_id"] == "user123"
        assert call_args[1]["extra"]["workspace_id"] == "workspace456"

    def test_get_context_logger(self):
        """Test get_context_logger function."""
        user_context = UserContext(user_id="user123", workspace_id="workspace456")

        with patch("logging.getLogger") as mock_get_logger:
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger

            context_logger = get_context_logger("test.logger", user_context)

            assert isinstance(context_logger, ContextLogger)
            assert context_logger.user_context == user_context


class TestWorkspaceContextFilter:
    """Test WorkspaceContextFilter class."""

    def test_filter_with_context(self):
        """Test filter with user context."""
        user_context = UserContext(user_id="user123", workspace_id="workspace456")
        filter_obj = WorkspaceContextFilter(user_context)

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        result = filter_obj.filter(record)

        assert result is True
        assert record.user_id == "user123"
        assert record.workspace_id == "workspace456"
        assert "[workspace:workspace456]" in record.msg
        assert "[user:user123]" in record.msg

    def test_filter_without_context(self):
        """Test filter without user context."""
        filter_obj = WorkspaceContextFilter()

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        result = filter_obj.filter(record)

        assert result is True
        assert not hasattr(record, "user_id")
        assert not hasattr(record, "workspace_id")
        assert record.msg == "Test message"


class TestWorkspaceContextFormatter:
    """Test WorkspaceContextFormatter class."""

    def test_format_with_workspace_context(self):
        """Test formatting with workspace context."""
        formatter = WorkspaceContextFormatter()

        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        record.user_id = "user123"
        record.workspace_id = "workspace456"

        formatted = formatter.format(record)
        parsed = json.loads(formatted)

        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "test.logger"
        assert parsed["message"] == "Test message"
        assert parsed["user_id"] == "user123"
        assert parsed["workspace_id"] == "workspace456"
        assert "timestamp" in parsed

    def test_format_with_audit_event(self):
        """Test formatting with audit event data."""
        formatter = WorkspaceContextFormatter()

        record = logging.LogRecord(
            name="test.audit",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="AUDIT: CREATE agent",
            args=(),
            exc_info=None,
        )
        record.audit_event = {
            "action": "create",
            "resource_type": "agent",
            "resource_id": "agent123",
        }

        formatted = formatter.format(record)
        parsed = json.loads(formatted)

        assert parsed["audit_event"]["action"] == "create"
        assert parsed["audit_event"]["resource_type"] == "agent"
        assert parsed["audit_event"]["resource_id"] == "agent123"


class TestAuditLogQuery:
    """Test AuditLogQuery class."""

    def test_query_logs_with_filters(self):
        """Test querying logs with filters."""
        # Create temporary log file
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
            # Write test log entries
            log_entries = [
                {
                    "timestamp": "2024-01-01T10:00:00Z",
                    "level": "INFO",
                    "message": "AUDIT: CREATE agent",
                    "user_id": "user123",
                    "workspace_id": "workspace456",
                    "audit_event": {
                        "action": "create",
                        "resource_type": "agent",
                        "resource_id": "agent123",
                    },
                },
                {
                    "timestamp": "2024-01-01T11:00:00Z",
                    "level": "INFO",
                    "message": "AUDIT: UPDATE task",
                    "user_id": "user456",
                    "workspace_id": "workspace456",
                    "audit_event": {
                        "action": "update",
                        "resource_type": "task",
                        "resource_id": "task123",
                    },
                },
            ]

            for entry in log_entries:
                f.write(json.dumps(entry) + "\n")

            temp_file = f.name

        try:
            query = AuditLogQuery(temp_file)

            # Test workspace filter
            results = query.query_logs(workspace_id="workspace456")
            assert len(results) == 2

            # Test user filter
            results = query.query_logs(user_id="user123")
            assert len(results) == 1
            assert results[0]["user_id"] == "user123"

            # Test resource type filter
            results = query.query_logs(resource_type="agent")
            assert len(results) == 1
            assert results[0]["audit_event"]["resource_type"] == "agent"

            # Test action filter
            results = query.query_logs(action="create")
            assert len(results) == 1
            assert results[0]["audit_event"]["action"] == "create"

            # Test limit
            results = query.query_logs(limit=1)
            assert len(results) == 1

        finally:
            import os

            os.unlink(temp_file)

    def test_get_user_activity(self):
        """Test getting user activity."""
        user_context = UserContext(user_id="user123", workspace_id="workspace456")

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
            log_entry = {
                "timestamp": "2024-01-01T10:00:00Z",
                "user_id": "user123",
                "workspace_id": "workspace456",
                "audit_event": {"action": "create", "resource_type": "agent"},
            }
            f.write(json.dumps(log_entry) + "\n")
            temp_file = f.name

        try:
            query = AuditLogQuery(temp_file)
            results = query.get_user_activity(user_context)

            assert len(results) == 1
            assert results[0]["user_id"] == "user123"
            assert results[0]["workspace_id"] == "workspace456"

        finally:
            import os

            os.unlink(temp_file)

    def test_get_workspace_activity(self):
        """Test getting workspace activity."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
            log_entry = {
                "timestamp": "2024-01-01T10:00:00Z",
                "user_id": "user123",
                "workspace_id": "workspace456",
                "audit_event": {"action": "create", "resource_type": "agent"},
            }
            f.write(json.dumps(log_entry) + "\n")
            temp_file = f.name

        try:
            query = AuditLogQuery(temp_file)
            results = query.get_workspace_activity("workspace456")

            assert len(results) == 1
            assert results[0]["workspace_id"] == "workspace456"

        finally:
            import os

            os.unlink(temp_file)

    def test_get_resource_history(self):
        """Test getting resource history."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
            log_entry = {
                "timestamp": "2024-01-01T10:00:00Z",
                "user_id": "user123",
                "workspace_id": "workspace456",
                "audit_event": {
                    "action": "create",
                    "resource_type": "agent",
                    "resource_id": "agent123",
                },
            }
            f.write(json.dumps(log_entry) + "\n")
            temp_file = f.name

        try:
            query = AuditLogQuery(temp_file)
            results = query.get_resource_history("agent", "agent123")

            assert len(results) == 1
            assert results[0]["audit_event"]["resource_id"] == "agent123"

        finally:
            import os

            os.unlink(temp_file)

    def test_get_error_logs(self):
        """Test getting error logs."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
            log_entry = {
                "timestamp": "2024-01-01T10:00:00Z",
                "user_id": "user123",
                "workspace_id": "workspace456",
                "audit_event": {
                    "action": "error",
                    "resource_type": "agent",
                    "error": "Database connection failed",
                },
            }
            f.write(json.dumps(log_entry) + "\n")
            temp_file = f.name

        try:
            query = AuditLogQuery(temp_file)
            results = query.get_error_logs(workspace_id="workspace456")

            assert len(results) == 1
            assert results[0]["audit_event"]["action"] == "error"

        finally:
            import os

            os.unlink(temp_file)
