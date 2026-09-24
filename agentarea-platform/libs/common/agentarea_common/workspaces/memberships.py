"""Workspace membership operations backed by the configured relationship graph."""

from __future__ import annotations

from agentarea_common.config import get_settings
from agentarea_common.di.container import get_container
from agentarea_common.rebac import (
    CheckResult,
    KetoClient,
    KetoError,
    OpenFGAClient,
    OpenFGAError,
    RelationQuery,
    RelationTuple,
)

MembershipGraph = KetoClient | OpenFGAClient


def get_workspace_membership_graph() -> MembershipGraph | None:
    """Resolve the configured relationship graph for workspace memberships."""
    settings = get_settings()
    if settings.access_control.ACCESS_CONTROL_BACKEND == "openfga":
        try:
            return get_container().get(OpenFGAClient)
        except ValueError:
            return OpenFGAClient(
                api_url=settings.openfga.ACCESS_CONTROL_OPENFGA_API_URL,
                store_id=settings.openfga.ACCESS_CONTROL_OPENFGA_STORE_ID,
                authorization_model_id=settings.openfga.ACCESS_CONTROL_OPENFGA_AUTHORIZATION_MODEL_ID,
                timeout_seconds=settings.openfga.ACCESS_CONTROL_OPENFGA_TIMEOUT_SECONDS,
                api_token=settings.openfga.ACCESS_CONTROL_OPENFGA_API_TOKEN or None,
            )
    if settings.access_control.ACCESS_CONTROL_BACKEND == "keto":
        try:
            return get_container().get(KetoClient)
        except ValueError:
            return KetoClient(
                read_url=settings.keto.ACCESS_CONTROL_KETO_READ_URL,
                write_url=settings.keto.ACCESS_CONTROL_KETO_WRITE_URL,
                timeout_seconds=settings.keto.ACCESS_CONTROL_KETO_TIMEOUT_SECONDS,
            )
    return None


def workspace_membership(workspace_id: str, user_id: str) -> RelationTuple:
    return RelationTuple(
        namespace="Workspace",
        object=workspace_id,
        relation="members",
        subject_id=_user_subject(user_id),
    )


async def check_workspace_membership(
    graph: MembershipGraph,
    *,
    workspace_id: str,
    user_id: str,
) -> bool:
    result: CheckResult = await graph.check(
        namespace="Workspace",
        object=workspace_id,
        relation="members",
        subject_id=_user_subject(user_id),
    )
    return result.allowed


async def list_workspace_member_ids(graph: MembershipGraph, workspace_id: str) -> list[str]:
    relationships = await graph.query_all_tuples(
        RelationQuery(namespace="Workspace", object=workspace_id, relation="members")
    )
    member_ids = {
        _user_id_from_subject(relationship.subject_id)
        for relationship in relationships
        if relationship.subject_id and relationship.subject_id.startswith("User:")
    }
    return sorted(member_ids)


async def list_workspace_ids_for_member(graph: MembershipGraph, user_id: str) -> list[str]:
    relationships = await graph.query_all_tuples(
        RelationQuery(namespace="Workspace", relation="members", subject_id=_user_subject(user_id))
    )
    workspace_ids = {
        relationship.object
        for relationship in relationships
        if relationship.namespace == "Workspace" and relationship.relation == "members"
    }
    return sorted(workspace_ids)


def workspace_baseline_role(workspace_id: str, user_id: str) -> RelationTuple:
    """The role a plain member holds over everything in the workspace.

    ``Workspace#members`` on its own confers nothing: the model gives the root
    project ``reader or ... or admin from workspace``, with no branch for a
    member. Membership therefore has to *grant* something, and what it grants is
    read over the root project, which cascades to every resource hung off it.

    Read and no more, because that is what membership already meant in practice:
    the workspace-scoped repository showed a member every row, while the graph
    refused them ``can_write`` on anything they did not create. The difference is
    that the grant is now a tuple somebody can see, audit and take away.
    """
    return RelationTuple(
        namespace="project",
        object=f"{workspace_id}-root",
        relation="reader",
        subject_id=_user_subject(user_id),
    )


async def grant_workspace_membership(
    graph: MembershipGraph,
    *,
    workspace_id: str,
    user_id: str,
) -> None:
    for relationship in (
        workspace_membership(workspace_id, user_id),
        workspace_baseline_role(workspace_id, user_id),
    ):
        try:
            await graph.write_tuple(relationship)
        except (KetoError, OpenFGAError) as exc:
            if "already exist" in str(exc):
                continue
            raise


async def revoke_workspace_membership(
    graph: MembershipGraph,
    *,
    workspace_id: str,
    user_id: str,
) -> None:
    for relationship in (
        workspace_membership(workspace_id, user_id),
        workspace_baseline_role(workspace_id, user_id),
    ):
        try:
            await graph.delete_tuple(relationship)
        except (KetoError, OpenFGAError) as exc:
            if "did not exist" in str(exc) or "does not exist" in str(exc):
                continue
            raise


def _user_subject(user_id: str) -> str:
    return user_id if user_id.startswith("User:") else f"User:{user_id}"


def _user_id_from_subject(subject: str) -> str:
    return subject.split(":", 1)[1] if subject.startswith("User:") else subject
