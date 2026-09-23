"""Joining a workspace grants read; it does not merely record membership.

``Workspace#members`` confers nothing in the authorization model: the root
project reads ``reader or can_read from role_assignment or can_read from parent
or admin from workspace``, and none of those branches mention a member. Until
2026-09-23 that gap was invisible, because no read endpoint consulted the graph
-- the workspace-scoped repository answered every question instead. Wiring reads
to the graph makes membership have to say what it grants.
"""

from __future__ import annotations

import pytest
from agentarea_common.testing import RecordingGraph
from agentarea_common.workspaces.memberships import (
    grant_workspace_membership,
    revoke_workspace_membership,
    workspace_baseline_role,
)


class _Graph(RecordingGraph):
    """A RecordingGraph that answers membership checks from what it holds."""

    async def check(self, *, namespace: str, object: str, relation: str, subject_id: str):
        from agentarea_common.rebac.models import CheckResult

        return CheckResult(
            allowed=any(
                t.namespace == namespace
                and t.object == object
                and t.relation == relation
                and t.subject_id == subject_id
                for t in self.recorded
            )
        )


@pytest.mark.asyncio
async def test_joining_grants_read_over_the_root_project() -> None:
    graph = _Graph()

    await grant_workspace_membership(graph, workspace_id="ws-acme", user_id="user-1")

    assert workspace_baseline_role("ws-acme", "user-1") in graph.recorded
    reader = next(t for t in graph.recorded if t.relation == "reader")
    assert (reader.namespace, reader.object) == ("project", "ws-acme-root")
    assert reader.subject_id == "User:user-1"


@pytest.mark.asyncio
async def test_a_member_gets_read_and_nothing_further() -> None:
    """Read only: membership never meant write over somebody else's resource."""
    graph = _Graph()

    await grant_workspace_membership(graph, workspace_id="ws-acme", user_id="user-1")

    assert {t.relation for t in graph.recorded} == {"members", "reader"}


@pytest.mark.asyncio
async def test_leaving_takes_the_read_back() -> None:
    """A revoked member who kept `reader` would still see the whole workspace."""
    graph = _Graph()
    await grant_workspace_membership(graph, workspace_id="ws-acme", user_id="user-1")

    await revoke_workspace_membership(graph, workspace_id="ws-acme", user_id="user-1")

    assert graph.recorded == []


@pytest.mark.asyncio
async def test_a_member_from_before_the_role_existed_gets_it_on_rejoin() -> None:
    """Accepting an invitation must grant read even if the graph already says member."""
    from agentarea_common.workspaces.memberships import workspace_membership

    graph = _Graph()
    await graph.write_tuple(workspace_membership("ws-acme", "user-1"))

    await grant_workspace_membership(graph, workspace_id="ws-acme", user_id="user-1")

    assert workspace_baseline_role("ws-acme", "user-1") in graph.recorded


@pytest.mark.asyncio
async def test_leaving_takes_the_read_back_even_without_the_membership_tuple() -> None:
    """A stray `reader` outliving its membership would still expose the workspace."""
    graph = _Graph()
    await graph.write_tuple(workspace_baseline_role("ws-acme", "user-1"))

    await revoke_workspace_membership(graph, workspace_id="ws-acme", user_id="user-1")

    assert graph.recorded == []
