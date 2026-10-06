"""Repair ownership tuples for rows that reached the database without them.

Idempotent; safe to re-run. Run inside the API container so it inherits DB +
OpenFGA env:

    docker compose -f docker-compose.dev.yaml exec app \
        uv run python scripts/20260923_reconcile_resource_authz.py [--dry-run]

Two things go missing, and both leave the graph saying "no" about rows that are
plainly visible in the product:

1. **Resources created outside the HTTP routes.** Until 2026-09-23 the ownership
   grant lived at the route, so ``agentarea/agents.create`` and the three
   skill-creating tool methods in ``libs/agents`` wrote none. Those rows fail
   closed in ``OpenFGAPermissionService``: their own creator gets 403 on edit
   and delete. New rows are covered by ``WorkspaceScopedRepository.create``;
   this repairs the ones already written.

2. **The member baseline role.** ``Workspace#members`` grants nothing by itself
   -- the root project has no branch for a member -- so membership now also
   writes ``project:<ws>-root#reader``. Members who joined before that have the
   membership tuple and no role.

With ``--revoke-ended-memberships`` it also goes the other way, and deletes:

3. **Grants an ended membership left behind.** Removal ends the membership row
   first and the graph second; until the graph step was queued in the outbox, a
   failed graph call left ``Workspace#members`` and the root ``reader`` role in
   place. Those tuples are dropped for every user with no membership row who does
   not own the workspace. Members admitted before membership rows were written
   have no row either, which is why this runs only when asked for: check the
   ``--dry-run`` output first. It refuses to run at all while any grant it would
   delete belongs to the owner or to someone holding an accepted invitation.

``--backfill-memberships-from-graph`` writes those missing rows first:

4. **Members with no row.** Every ``Workspace#members`` user without a
   membership row, owners excepted, gets one, unless their membership was ended
   and only its graph revocation is outstanding. Run it, and read its warnings,
   before ``--revoke-ended-memberships``.

Steps 1 and 2 are ``agentarea_common.rebac.ownership_reconcile``, which
``agentarea-api reconcile`` also runs after every migration; this script adds
the membership repairs that need a person to read their output first.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections.abc import Awaitable, Callable

from agentarea_common.config import get_database, get_settings
from agentarea_common.rebac.models import RelationQuery, RelationTuple
from agentarea_common.rebac.openfga_bootstrap import bootstrap_openfga
from agentarea_common.rebac.openfga_client import OpenFGAClient
from agentarea_common.rebac.ownership import root_project_id
from agentarea_common.rebac.ownership_reconcile import (
    TupleWriter,
    load_workspace_owners,
    reconcile_member_roles,
    reconcile_resource_ownership,
)
from agentarea_common.workspaces.models import (
    INVITATION_STATUS_ACCEPTED,
    INVITATION_STATUS_REVOKED,
)
from agentarea_common.workspaces.repository import MEMBERSHIP_ENDED
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("reconcile_resource_authz")


async def reconcile_workspace_admins(writer: TupleWriter, owners: dict[str, str]) -> None:
    """Project each workspace's owner onto ``Workspace#admin``.

    Two representations of one fact: ``workspaces.owner_user_id`` answers
    ``requires_workspace_admin()``, while ``Workspace#admin`` is what OpenFGA
    evaluates in ``project.can_read: ... or admin from workspace`` -- the branch
    that lets an admin reach objects they do not own. They agree by construction
    at creation time and nothing changes ownership afterwards, but a seed that
    failed halfway leaves an admin who can rewrite policy and cannot open an
    agent. The column is the authority; this writes the projection.
    """
    for workspace_id, owner in owners.items():
        if not owner:
            logger.warning("workspace %s has no owner_user_id; skipped", workspace_id)
            continue
        await writer.ensure(
            RelationTuple(
                namespace="Workspace",
                object=workspace_id,
                relation="admin",
                subject_id=f"User:{owner}",
            )
        )
        await writer.ensure(
            RelationTuple(
                namespace="project",
                object=root_project_id(workspace_id),
                relation="workspace",
                subject_id=f"Workspace:{workspace_id}",
            )
        )


class RevocationRefused(Exception):  # noqa: N818
    """Revoking would take access from someone the database says belongs."""


_ACCEPTED_WITHOUT_ROW = text(
    """
    SELECT owner_user_id FROM workspaces WHERE id = :workspace_id
    UNION
    SELECT CAST(:workspace_id AS VARCHAR)
    WHERE NOT EXISTS (SELECT 1 FROM workspaces WHERE id = :workspace_id)
    UNION
    SELECT invitation.accepted_by_user_id
    FROM workspace_invitations AS invitation
    WHERE invitation.workspace_id = :workspace_id
      AND invitation.status = :accepted
      AND invitation.accepted_by_user_id IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM workspace_memberships AS membership
          WHERE membership.workspace_id = invitation.workspace_id
            AND membership.user_id = invitation.accepted_by_user_id
      )
    """
)


async def load_protected(session: AsyncSession, workspace_id: str) -> set[str]:
    """Who belongs to the workspace without a membership row saying so.

    The owner, whose access is not membership's, and whoever holds an accepted
    invitation the row was never written for. A workspace with no row is a
    personal one, owned by the user sharing its id.
    """
    rows = await session.execute(
        _ACCEPTED_WITHOUT_ROW,
        {"workspace_id": workspace_id, "accepted": INVITATION_STATUS_ACCEPTED},
    )
    return {str(user_id) for user_id in rows.scalars()}


async def _revoke_ended_memberships(
    writer: TupleWriter,
    client: OpenFGAClient,
    *,
    load_members: Callable[[str], Awaitable[set[str]]],
    load_protected: Callable[[str], Awaitable[set[str]]],
    owners: dict[str, str],
) -> int:
    """Delete the member grants of every user whose membership has ended.

    ``load_members`` reads a workspace's membership rows. It is called per
    workspace right before that workspace's tuples are deleted, so a member
    admitted while the run is under way keeps their grants. A workspace with no
    row in ``owners`` is a personal one, owned by the user sharing its id.

    ``load_protected`` reads who belongs without a row: the owner, and anyone
    holding an accepted invitation. Their missing row is a gap in the data, not
    an ended membership, so a grant of theirs refuses the whole run before
    anything is deleted.
    """
    root_suffix = root_project_id("")
    grants = await client.query_all_tuples(RelationQuery(namespace="Workspace", relation="members"))
    grants += [
        t
        for t in await client.query_all_tuples(
            RelationQuery(namespace="project", relation="reader")
        )
        if t.object.endswith(root_suffix)
    ]
    by_workspace: dict[str, list[tuple[str, RelationTuple]]] = {}
    for grant in grants:
        if not grant.subject_id or not grant.subject_id.startswith("User:"):
            continue
        user_id = grant.subject_id.removeprefix("User:")
        workspace_id = (
            grant.object.removesuffix(root_suffix) if grant.namespace == "project" else grant.object
        )
        if owners.get(workspace_id, workspace_id) == user_id:
            continue
        by_workspace.setdefault(workspace_id, []).append((user_id, grant))
    refused: set[str] = set()
    for workspace_id, candidates in by_workspace.items():
        protected = await load_protected(workspace_id)
        refused |= {
            f"User:{user_id} in Workspace:{workspace_id}"
            for user_id, _ in candidates
            if user_id in protected
        }
    if refused:
        raise RevocationRefused(
            "refusing to revoke ended memberships: these users own the workspace or hold an "
            "accepted invitation, yet have no membership row. Backfill the rows first "
            "(alembic upgrade head, then --backfill-memberships-from-graph): "
            + ", ".join(sorted(refused))
        )
    for workspace_id, candidates in by_workspace.items():
        members = await load_members(workspace_id)
        for user_id, grant in candidates:
            if user_id not in members:
                await writer.remove(grant)
    return writer.deleted


_MEMBERSHIP_STATE = text(
    """
    SELECT
        EXISTS (
            SELECT 1 FROM workspace_memberships
            WHERE workspace_id = :workspace_id AND user_id = :user_id
        ) AS present,
        EXISTS (
            SELECT 1 FROM workspace_invitations
            WHERE workspace_id = :workspace_id
              AND accepted_by_user_id = :user_id
              AND status = :revoked
        )
        OR EXISTS (
            SELECT 1 FROM event_outbox
            WHERE event_type = :ended
              AND workspace_id = :workspace_id
              AND aggregate_id = :user_id
              AND published_at IS NULL
        ) AS ended
    """
)

_INSERT_MEMBERSHIP = text(
    """
    INSERT INTO workspace_memberships
        (id, workspace_id, user_id, invitation_id, created_at, updated_at)
    SELECT gen_random_uuid(), :workspace_id, :user_id, invitation.id, joined.at, joined.at
    FROM (
        SELECT COALESCE(
            (
                SELECT min(accepted_at) FROM workspace_invitations
                WHERE workspace_id = :workspace_id
                  AND accepted_by_user_id = :user_id
                  AND status = :accepted
            ),
            (SELECT created_at FROM workspaces WHERE id = :workspace_id),
            timezone('utc', now())
        ) AS at
    ) AS joined
    LEFT JOIN LATERAL (
        SELECT id FROM workspace_invitations
        WHERE workspace_id = :workspace_id
          AND accepted_by_user_id = :user_id
          AND status = :accepted
        ORDER BY accepted_at NULLS LAST
        LIMIT 1
    ) AS invitation ON true
    ON CONFLICT (workspace_id, user_id) DO NOTHING
    """
)


async def record_membership(
    session: AsyncSession, workspace_id: str, user_id: str, *, dry_run: bool
) -> str:
    """Write the row of a graph member who has none; say which case it was.

    ``present``: the row exists. ``ended``: the membership was ended and its
    graph revocation has not landed yet -- an invitation they joined through is
    revoked, or the removal is still queued in the outbox -- so writing a row
    would undo the removal. ``recorded``: the row is written (or would be).

    The join date is the accepted invitation's, else the workspace's creation,
    else now, for a member neither recorded.
    """
    state = (
        await session.execute(
            _MEMBERSHIP_STATE,
            {
                "workspace_id": workspace_id,
                "user_id": user_id,
                "revoked": INVITATION_STATUS_REVOKED,
                "ended": MEMBERSHIP_ENDED,
            },
        )
    ).one()
    if state.present:
        return "present"
    if state.ended:
        return "ended"
    if not dry_run:
        await session.execute(
            _INSERT_MEMBERSHIP,
            {
                "workspace_id": workspace_id,
                "user_id": user_id,
                "accepted": INVITATION_STATUS_ACCEPTED,
            },
        )
    return "recorded"


async def _backfill_memberships_from_graph(
    client: OpenFGAClient,
    *,
    record: Callable[[str, str], Awaitable[str]],
    rows: set[tuple[str, str]],
    owners: dict[str, str],
) -> dict[str, int]:
    """Give every ``Workspace#members`` user a membership row, owners excepted.

    The graph is what authorization reads, and the row is what removal and
    ``--revoke-ended-memberships`` read, so the two must agree before either
    runs. ``rows`` are the (workspace, user) pairs already recorded. A row with
    no graph membership is reported, never deleted: it is either a member whose
    graph grant was lost, or a member removed before removals revoked their
    invitation, and only a person can tell which.
    """
    members: set[tuple[str, str]] = set()
    for membership in await client.query_all_tuples(
        RelationQuery(namespace="Workspace", relation="members")
    ):
        if not membership.subject_id or not membership.subject_id.startswith("User:"):
            continue
        members.add((membership.object, membership.subject_id.removeprefix("User:")))

    outcomes = {"recorded": 0, "present": 0, "ended": 0}
    for workspace_id, user_id in sorted(members - rows):
        if owners.get(workspace_id, workspace_id) == user_id:
            continue
        outcome = await record(workspace_id, user_id)
        outcomes[outcome] += 1
        if outcome == "ended":
            logger.warning(
                "User:%s in Workspace:%s: membership ended, graph grant still present; "
                "--revoke-ended-memberships takes it back",
                user_id,
                workspace_id,
            )
    for workspace_id, user_id in sorted(rows - members):
        if owners.get(workspace_id, workspace_id) == user_id:
            continue
        logger.warning(
            "User:%s in Workspace:%s has a membership row and no graph membership; review it",
            user_id,
            workspace_id,
        )
    return outcomes


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="report what would be written, write nothing"
    )
    parser.add_argument(
        "--revoke-ended-memberships",
        action="store_true",
        help="also delete member grants of users with no membership row (owners excepted)",
    )
    parser.add_argument(
        "--backfill-memberships-from-graph",
        action="store_true",
        help="write the missing membership row of every Workspace#members user (owners excepted)",
    )
    args = parser.parse_args()

    settings = get_settings()
    if settings.access_control.BACKEND != "openfga":
        raise SystemExit(
            f"AGENTAREA_AUTHZ_BACKEND={settings.access_control.BACKEND!r}; "
            "this reconcile targets OpenFGA."
        )

    await bootstrap_openfga(settings.openfga)
    client = OpenFGAClient(
        api_url=settings.openfga.URL,
        store_id=settings.openfga.STORE_ID,
        authorization_model_id=settings.openfga.MODEL_ID,
        timeout_seconds=settings.openfga.TIMEOUT.total_seconds(),
    )
    writer = TupleWriter(
        client, args.dry_run, await client.query_all_tuples(RelationQuery())
    )

    database = get_database()
    resource_count = 0
    try:
        async with database.async_session_factory() as session:
            workspace_owners = await load_workspace_owners(session)
            resource_count = await reconcile_resource_ownership(session, writer, workspace_owners)

        await reconcile_workspace_admins(writer, workspace_owners)
        logger.info("reconciled admin projections for %d workspaces", len(workspace_owners))

        if args.backfill_memberships_from_graph:
            async with database.async_session_factory() as session:
                recorded_rows = {
                    (str(row.workspace_id), str(row.user_id))
                    for row in (
                        await session.execute(
                            text("SELECT workspace_id, user_id FROM workspace_memberships")
                        )
                    ).all()
                }

            async def record(workspace_id: str, user_id: str) -> str:
                async with database.async_session_factory() as session:
                    outcome = await record_membership(
                        session, workspace_id, user_id, dry_run=args.dry_run
                    )
                    await session.commit()
                    return outcome

            outcomes = await _backfill_memberships_from_graph(
                client, record=record, rows=recorded_rows, owners=workspace_owners
            )
            logger.info(
                "%s %d membership rows from the graph (%d ended, %d written meanwhile)",
                "would write" if args.dry_run else "wrote",
                outcomes["recorded"],
                outcomes["ended"],
                outcomes["present"],
            )

        if args.revoke_ended_memberships:

            async def load_protected_users(workspace_id: str) -> set[str]:
                async with database.async_session_factory() as session:
                    return await load_protected(session, workspace_id)

            async def load_members(workspace_id: str) -> set[str]:
                async with database.async_session_factory() as session:
                    rows = await session.execute(
                        text(
                            "SELECT user_id FROM workspace_memberships "
                            "WHERE workspace_id = :workspace_id"
                        ),
                        {"workspace_id": workspace_id},
                    )
                    return {str(user_id) for user_id in rows.scalars()}

            revoked = await _revoke_ended_memberships(
                writer,
                client,
                load_members=load_members,
                load_protected=load_protected_users,
                owners=workspace_owners,
            )
            logger.info(
                "%s %d grants of ended memberships",
                "would delete" if args.dry_run else "deleted",
                revoked,
            )

        members = await reconcile_member_roles(writer, client)
        logger.info("reconciled baseline roles for %d workspace memberships", members)
    finally:
        await client.aclose()

    logger.info(
        "%s: %d tuples across %d resources",
        "would write" if args.dry_run else "wrote",
        writer.written,
        resource_count,
    )


if __name__ == "__main__":
    asyncio.run(main())
