"""Backfill baseline governance policies for pre-existing workspaces.

The workspace-creation hook seeds defaults for newly created workspaces; this
one-shot script covers workspaces that already existed before the feature
landed. Idempotent per policy dimension: existing rules are never overwritten,
while missing baseline dimensions are inserted as additional rows.

Usage::

    cd agentarea-platform
    uv run python scripts/backfill_default_policies.py            # all workspaces
    uv run python scripts/backfill_default_policies.py <ws_id>    # one workspace
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from agentarea_common.auth.context import UserContext
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.config.database import db
from agentarea_common.workspaces import Workspace
from agentarea_governance.application import (
    GovernancePolicyService,
    provision_default_policies,
)
from sqlalchemy import select

logger = logging.getLogger(__name__)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "workspace_id",
        nargs="?",
        help="single workspace to seed; default: every workspace",
    )
    args = parser.parse_args()

    async with db.session() as session:
        if args.workspace_id:
            row = (
                await session.execute(
                    select(Workspace.id, Workspace.owner_user_id).where(
                        Workspace.id == args.workspace_id
                    )
                )
            ).first()
            if row is None:
                raise SystemExit(f"workspace {args.workspace_id!r} not found")
            targets = [row]
        else:
            targets = (await session.execute(select(Workspace.id, Workspace.owner_user_id))).all()

        total = 0
        for ws_id, owner_user_id in targets:
            ctx = UserContext(
                user_id=owner_user_id or "backfill-script",
                workspace_id=ws_id,
            )
            governance = GovernancePolicyService(RepositoryFactory(session, ctx))
            created = await provision_default_policies(governance, ws_id)
            if created:
                await session.commit()
                total += len(created)
                logger.info("seeded %s policies for workspace %s", len(created), ws_id)
            else:
                logger.info("skipped %s (already has policies)", ws_id)

        logger.info("done: %s policies created across %s workspace(s)", total, len(targets))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    asyncio.run(main())
