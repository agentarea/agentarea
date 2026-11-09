"""How /v1/bundles/install answers a bundle it cannot install."""

import pytest
from agentarea_agents.application.agent_service import (
    InvalidClientError,
    InvalidMcpToolError,
    ReasoningConflictError,
)
from agentarea_api.api.v1.bundles import InstallRequest, install_bundle
from agentarea_bundles.application.installer import BundleInstallError, BundleValidationError
from agentarea_bundles.application.service import BundlePlanChangedError
from agentarea_bundles.schemas.bundle import Bundle
from agentarea_common.exceptions.errors import AppError


class _Refusing:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    async def install(self, bundle, setup_values, plan_digest):
        raise self.exc


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exc", "status", "code"),
    [
        (BundleValidationError("skill 'sk' is not a valid SKILL.md: bad"), 422, "bundle_invalid"),
        (
            BundleInstallError("failed to import skill 'sk' from https://github.com/o/r"),
            400,
            "bundle_install_failed",
        ),
        (BundlePlanChangedError("the deploy plan changed"), 409, "bundle_plan_changed"),
        (
            InvalidMcpToolError("2 MCP connections here are named 'gh'"),
            400,
            "bundle_install_failed",
        ),
        (InvalidClientError("Client 'x' is no Codex client"), 400, "bundle_install_failed"),
        (ReasoningConflictError(), 400, "bundle_install_failed"),
    ],
)
async def test_an_invalid_bundle_is_422_and_a_failed_install_is_400(exc, status, code):
    body = InstallRequest(bundle=Bundle(name="b"), plan_digest="d")

    with pytest.raises(AppError) as refused:
        await install_bundle(body, _Refusing(exc))  # type: ignore[arg-type]

    problem = refused.value.to_problem()
    assert (problem["status"], problem["code"]) == (status, code)
    assert problem["detail"] == str(exc)
    assert problem["issues"] == []
