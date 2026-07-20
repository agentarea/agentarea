"""Single PDP for concrete tool invocation authorization."""

from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agentarea_common.rebac.openfga_client import OpenFGAClient

logger = logging.getLogger(__name__)


class ToolAuthorizationAction(StrEnum):
    """Authorization verdict for a concrete tool invocation."""

    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


@dataclass(frozen=True)
class ToolAuthorizationRequest:
    """Inputs to the tool invocation PDP.

    ``policy_required`` means the caller is executing inside a resolved task
    policy snapshot. Direct MCP proxy calls do not have that snapshot, so they
    still use this PDP but go straight to the graph-backed concrete grant.
    """

    tool_name: str
    tool_args: dict[str, Any]
    user_id: str | None = None
    workspace_id: str | None = None
    effective_policy: dict[str, Any] | None = None
    policy_required: bool = True


@dataclass(frozen=True)
class ToolAuthorizationDecision:
    """PDP result consumed by PEP call sites."""

    action: ToolAuthorizationAction
    reason: str

    @property
    def allowed(self) -> bool:
        return self.action is ToolAuthorizationAction.ALLOW


async def authorize_tool_invocation(
    request: ToolAuthorizationRequest,
    *,
    openfga_client: OpenFGAClient | None = None,
) -> ToolAuthorizationDecision:
    """Decide whether a concrete tool invocation may run.

    This is the single runtime PDP. It evaluates the task policy snapshot and,
    when the policy does not explicitly grant all invocations, delegates the
    concrete user/tool/args resource decision to the configured graph backend.
    """
    if request.policy_required:
        # Task paths carry a resolved policy snapshot that is authoritative:
        # composition + policy already decided allow / deny / approval. The graph
        # is not consulted here — disclosure, the workflow gate, and this activity
        # all read the one snapshot, so there is no path where disclosure says yes
        # and enforcement says no. The graph remains only for the policy-less MCP
        # proxy path below, which has no snapshot to consult.
        return decide_tool_policy(request.effective_policy, request.tool_name)

    if not request.user_id:
        return ToolAuthorizationDecision(
            ToolAuthorizationAction.DENY,
            "missing user_id for tool authorization",
        )
    if not request.workspace_id:
        return ToolAuthorizationDecision(
            ToolAuthorizationAction.DENY,
            "missing workspace_id for tool authorization",
        )

    from agentarea_common.config import get_settings

    settings = get_settings()
    if settings.access_control.ACCESS_CONTROL_BACKEND != "openfga":
        return ToolAuthorizationDecision(
            ToolAuthorizationAction.DENY,
            "OpenFGA tool authorization is disabled",
        )

    openfga = openfga_client or _resolve_openfga_client()
    if openfga is None:
        return ToolAuthorizationDecision(
            ToolAuthorizationAction.DENY,
            "OpenFGA tool authorization unavailable",
        )

    from .tool_invocation import is_tool_invocation_allowed

    allowed = await is_tool_invocation_allowed(
        openfga,
        user_id=request.user_id,
        workspace_id=request.workspace_id,
        tool_name=request.tool_name,
        tool_args=request.tool_args,
    )
    if not allowed:
        return ToolAuthorizationDecision(
            ToolAuthorizationAction.DENY,
            "OpenFGA denied this tool invocation",
        )
    return ToolAuthorizationDecision(ToolAuthorizationAction.ALLOW, "allowed by graph policy")


def decide_tool_policy(
    effective_policy: dict[str, Any] | None, tool_name: str
) -> ToolAuthorizationDecision:
    """Evaluate only the task policy portion of a tool invocation decision.

    Default-allow: this function only ever judges a tool the agent is already
    composed with (that is why it is being asked about), so composition is the
    allow. Policy subtracts from it — a ``denied`` match, or a non-empty
    ``allowed`` allowlist the tool falls outside of, or an approval requirement.
    An absent/empty allowlist is "no allowlist in use", not "deny everything";
    restriction is expressed by composing fewer tools or by DENY rules.
    """
    tools = (effective_policy or {}).get("tools") or {}

    denied = tools.get("denied") or []
    if _matches_any(tool_name, denied):
        return ToolAuthorizationDecision(
            ToolAuthorizationAction.DENY,
            f"tool '{tool_name}' is denied by policy",
        )

    allowed = tools.get("allowed")
    if allowed and not _matches_any(tool_name, allowed):
        return ToolAuthorizationDecision(
            ToolAuthorizationAction.DENY,
            f"tool '{tool_name}' is not permitted by the policy allowlist",
        )

    approval = (effective_policy or {}).get("approval") or {}
    if approval.get("requires_human_approval") is True or tool_name in (
        approval.get("escalation_rules") or []
    ):
        return ToolAuthorizationDecision(
            ToolAuthorizationAction.REQUIRE_APPROVAL,
            f"tool '{tool_name}' requires approval",
        )

    return ToolAuthorizationDecision(ToolAuthorizationAction.ALLOW, "allowed by task policy")


def _matches_any(name: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in patterns)


def _resolve_openfga_client() -> OpenFGAClient | None:
    from agentarea_common.config import get_settings
    from agentarea_common.di.container import get_container
    from agentarea_common.rebac.openfga_client import OpenFGAClient

    settings = get_settings()
    try:
        try:
            return get_container().get(OpenFGAClient)
        except ValueError:
            return OpenFGAClient(
                api_url=settings.openfga.ACCESS_CONTROL_OPENFGA_API_URL,
                store_id=settings.openfga.ACCESS_CONTROL_OPENFGA_STORE_ID,
                authorization_model_id=settings.openfga.ACCESS_CONTROL_OPENFGA_AUTHORIZATION_MODEL_ID,
                timeout_seconds=settings.openfga.ACCESS_CONTROL_OPENFGA_TIMEOUT_SECONDS,
            )
    except Exception:
        logger.exception("OpenFGA tool authorization client unavailable")
        return None
