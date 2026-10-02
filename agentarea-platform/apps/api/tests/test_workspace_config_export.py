import pytest
from agentarea_api.api.v1.workspace_config import export_workspace_config
from fastapi import HTTPException


class UnrepresentableWorkspaceExport:
    async def export_workspace(self):
        raise ValueError("Skill 'Remote Skill' has no inline content")


@pytest.mark.asyncio
async def test_export_returns_validation_error_for_unrepresentable_workspace():
    with pytest.raises(HTTPException) as exc_info:
        await export_workspace_config(
            user_context=None,
            service=UnrepresentableWorkspaceExport(),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "Skill 'Remote Skill' has no inline content"
