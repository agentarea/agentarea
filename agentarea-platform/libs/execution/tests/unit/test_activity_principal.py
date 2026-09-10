"""Activities run as the task's principal, never as a fabricated one.

`create_system_context(workspace_id)` used to default `user_id` to the
workspace id, so every activity that skipped the argument ran as a principal
that had never authenticated. The workflow always knows the real user —
`AgentExecutionRequest.user_id` is required — so the fix is to carry it down,
not to invent it.
"""

import pytest

from agentarea_execution import models
from agentarea_execution.activities.dependencies import create_user_context

# Every activity request that previously reached create_system_context().
PRINCIPAL_CARRYING_REQUESTS = [
    "ArtifactValidationRequest",
    "LLMCallRequest",
    "MCPToolRequest",
    "UpdateTaskStatusRequest",
    "UpdateTaskGovernanceSnapshotRequest",
    "CompactMessagesRequest",
    "ResolveAgentToolsRequest",
    "RecallHistoryRequest",
    "MaterializeSkillFilesRequest",
    "ResolveModelRequest",
]


class TestNoFabricatedPrincipal:
    def test_create_system_context_is_gone(self):
        """It had no safe call: the only argument it needed was a workspace."""
        from agentarea_execution.activities import dependencies

        assert not hasattr(dependencies, "create_system_context")

    def test_missing_user_id_raises(self):
        with pytest.raises(ValueError, match="user_id"):
            create_user_context({"workspace_id": "ws-1"})

    def test_empty_user_id_raises(self):
        with pytest.raises(ValueError, match="user_id"):
            create_user_context({"user_id": "", "workspace_id": "ws-1"})

    def test_missing_workspace_id_raises(self):
        with pytest.raises(ValueError, match="workspace_id"):
            create_user_context({"user_id": "user-1"})

    def test_real_principal_is_carried_through(self):
        ctx = create_user_context({"user_id": "user-1", "workspace_id": "ws-1"})
        assert ctx.user_id == "user-1"
        assert ctx.workspace_id == "ws-1"
        assert ctx.accessible_workspaces == ["ws-1"]

    def test_workspace_id_is_never_reused_as_user_id(self):
        """The exact old behaviour, pinned so it cannot come back."""
        with pytest.raises(ValueError):
            create_user_context({"workspace_id": "ws-1", "user_id": None})


class TestActivityRequestsCarryPrincipal:
    @pytest.mark.parametrize("request_name", PRINCIPAL_CARRYING_REQUESTS)
    def test_request_has_user_context_data_field(self, request_name):
        """Without this field the activity has no principal to run as."""
        request_cls = getattr(models, request_name)
        assert "user_context_data" in request_cls.model_fields, (
            f"{request_name} reaches an activity that needs a principal, "
            "so it must carry user_context_data"
        )
