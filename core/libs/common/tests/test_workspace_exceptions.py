"""Tests for workspace exception handling."""

from unittest.mock import Mock, patch

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.context_manager import ContextManager
from agentarea_common.exceptions.handlers import (
    invalid_jwt_token_handler,
    missing_workspace_context_handler,
    workspace_access_denied_handler,
    workspace_error_handler,
    workspace_resource_not_found_handler,
)
from agentarea_common.exceptions.utils import (
    check_workspace_access,
    ensure_workspace_resource_exists,
    raise_workspace_access_denied,
    raise_workspace_resource_not_found,
)
from agentarea_common.exceptions.workspace import (
    InvalidJWTToken,
    MissingWorkspaceContext,
    WorkspaceAccessDenied,
    WorkspaceError,
    WorkspaceResourceNotFound,
)
from fastapi import Request, status
from fastapi.responses import JSONResponse


class TestWorkspaceExceptions:
    """Test workspace exception classes."""

    def test_workspace_error_base_class(self):
        """Test WorkspaceError base class."""
        error = WorkspaceError(
            message="Test error", workspace_id="ws-123", user_id="user-456", resource_id="res-789"
        )

        assert (
            str(error) == "Test error (workspace_id=ws-123, user_id=user-456, resource_id=res-789)"
        )
        assert error.workspace_id == "ws-123"
        assert error.user_id == "user-456"
        assert error.resource_id == "res-789"

    def test_workspace_access_denied(self):
        """Test WorkspaceAccessDenied exception."""
        error = WorkspaceAccessDenied(
            resource_type="agent",
            resource_id="agent-123",
            current_workspace_id="ws-current",
            resource_workspace_id="ws-other",
            user_id="user-456",
        )

        assert "Access denied to agent 'agent-123'" in str(error)
        assert "workspace 'ws-other'" in str(error)
        assert "workspace 'ws-current'" in str(error)
        assert error.resource_type == "agent"
        assert error.current_workspace_id == "ws-current"
        assert error.resource_workspace_id == "ws-other"

    def test_missing_workspace_context(self):
        """Test MissingWorkspaceContext exception."""
        error = MissingWorkspaceContext(missing_field="workspace_id", user_id="user-456")

        assert "Missing required context field: workspace_id" in str(error)
        assert error.missing_field == "workspace_id"
        assert error.user_id == "user-456"

    def test_invalid_jwt_token(self):
        """Test InvalidJWTToken exception."""
        error = InvalidJWTToken(reason="Token expired", token_present=True)

        assert "Invalid JWT token: Token expired" in str(error)
        assert error.reason == "Token expired"
        assert error.token_present is True

    def test_workspace_resource_not_found(self):
        """Test WorkspaceResourceNotFound exception."""
        error = WorkspaceResourceNotFound(
            resource_type="task", resource_id="task-123", workspace_id="ws-123", user_id="user-456"
        )

        assert "Task 'task-123' not found in workspace 'ws-123'" in str(error)
        assert error.resource_type == "task"


class TestWorkspaceErrorHandlers:
    """Test workspace error handlers."""

    @pytest.fixture
    def mock_request(self):
        """Create a mock FastAPI request."""
        request = Mock(spec=Request)
        request.method = "GET"
        request.url = Mock()
        request.url.path = "/api/v1/agents/123"
        request.url.__str__ = Mock(return_value="http://localhost/api/v1/agents/123")
        return request

    @pytest.fixture
    def user_context(self):
        """Create a test user context."""
        return UserContext(user_id="test-user", workspace_id="test-workspace", roles=["user"])

    @pytest.mark.asyncio
    async def test_workspace_access_denied_handler(self, mock_request):
        """Test workspace access denied handler returns 404."""
        error = WorkspaceAccessDenied(
            resource_type="agent",
            resource_id="agent-123",
            current_workspace_id="ws-current",
            resource_workspace_id="ws-other",
        )

        response = await workspace_access_denied_handler(mock_request, error)

        assert isinstance(response, JSONResponse)
        assert response.status_code == status.HTTP_404_NOT_FOUND

        # Check response content
        content = response.body.decode()
        assert "Resource not found" in content
        assert "RESOURCE_NOT_FOUND" in content

    @pytest.mark.asyncio
    async def test_workspace_resource_not_found_handler(self, mock_request):
        """Test workspace resource not found handler."""
        error = WorkspaceResourceNotFound(
            resource_type="task", resource_id="task-123", workspace_id="ws-123"
        )

        response = await workspace_resource_not_found_handler(mock_request, error)

        assert isinstance(response, JSONResponse)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.asyncio
    async def test_missing_workspace_context_handler(self, mock_request):
        """Test missing workspace context handler."""
        error = MissingWorkspaceContext(missing_field="workspace_id")

        response = await missing_workspace_context_handler(mock_request, error)

        assert isinstance(response, JSONResponse)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.asyncio
    async def test_invalid_jwt_token_handler(self, mock_request):
        """Test invalid JWT token handler."""
        error = InvalidJWTToken(reason="Token expired", token_present=True)

        response = await invalid_jwt_token_handler(mock_request, error)

        assert isinstance(response, JSONResponse)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert "WWW-Authenticate" in response.headers

    @pytest.mark.asyncio
    async def test_workspace_error_handler(self, mock_request):
        """Test generic workspace error handler."""
        error = WorkspaceError("Generic workspace error")

        response = await workspace_error_handler(mock_request, error)

        assert isinstance(response, JSONResponse)
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    @pytest.mark.asyncio
    @patch("agentarea_common.exceptions.handlers.ContextManager.get_context")
    async def test_workspace_headers_included(self, mock_get_context, mock_request, user_context):
        """Test that workspace headers are included in responses."""
        mock_get_context.return_value = user_context

        error = WorkspaceResourceNotFound(
            resource_type="agent", resource_id="agent-123", workspace_id="test-workspace"
        )

        response = await workspace_resource_not_found_handler(mock_request, error)

        assert "X-Workspace-ID" in response.headers
        assert response.headers["X-Workspace-ID"] == "test-workspace"


class TestWorkspaceUtilities:
    """Test workspace utility functions."""

    @pytest.fixture
    def user_context(self):
        """Create a test user context."""
        return UserContext(user_id="test-user", workspace_id="test-workspace", roles=["user"])

    def test_raise_workspace_access_denied(self, user_context):
        """Test raise_workspace_access_denied utility."""
        ContextManager.set_context(user_context)

        with pytest.raises(WorkspaceAccessDenied) as exc_info:
            raise_workspace_access_denied("agent", "agent-123", "other-workspace")

        error = exc_info.value
        assert error.resource_type == "agent"
        assert error.resource_id == "agent-123"
        assert error.current_workspace_id == "test-workspace"
        assert error.resource_workspace_id == "other-workspace"

        ContextManager.clear_context()

    def test_raise_workspace_resource_not_found(self, user_context):
        """Test raise_workspace_resource_not_found utility."""
        ContextManager.set_context(user_context)

        with pytest.raises(WorkspaceResourceNotFound) as exc_info:
            raise_workspace_resource_not_found("task", "task-123")

        error = exc_info.value
        assert error.resource_type == "task"
        assert error.resource_id == "task-123"
        assert error.workspace_id == "test-workspace"

        ContextManager.clear_context()

    def test_check_workspace_access_success(self, user_context):
        """Test check_workspace_access with valid access."""
        ContextManager.set_context(user_context)

        # Should not raise exception
        check_workspace_access("test-workspace", "agent", "agent-123")

        ContextManager.clear_context()

    def test_check_workspace_access_denied(self, user_context):
        """Test check_workspace_access with invalid access."""
        ContextManager.set_context(user_context)

        with pytest.raises(WorkspaceAccessDenied):
            check_workspace_access("other-workspace", "agent", "agent-123")

        ContextManager.clear_context()

    def test_ensure_workspace_resource_exists_success(self):
        """Test ensure_workspace_resource_exists with existing resource."""
        resource = {"id": "123", "name": "test"}

        result = ensure_workspace_resource_exists(resource, "agent", "agent-123")

        assert result == resource

    def test_ensure_workspace_resource_exists_not_found(self):
        """Test ensure_workspace_resource_exists with None resource."""
        with pytest.raises(WorkspaceResourceNotFound):
            ensure_workspace_resource_exists(None, "agent", "agent-123")
