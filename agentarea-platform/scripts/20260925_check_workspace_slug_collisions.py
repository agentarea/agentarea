"""Report workspace slugs that could impersonate another workspace's id.

Read-only; exits 1 when it finds any. Run inside the API container so it
inherits the DB env:

    docker compose -f docker-compose.dev.yaml exec app \
        uv run python scripts/20260925_check_workspace_slug_collisions.py

A UUID-shaped workspace reference now resolves by id only, and ``slugify``
never mints a UUID-shaped slug. Rows written before that could still carry
one: a shared workspace named after someone's user id got that id as its slug,
and a personal workspace is keyed by its owner's user id. Such a slug no longer
captures anything, but its owner cannot reach the workspace by it either
(the reference resolves as an id), so each hit needs a new slug.

Two findings:

1. **Shadowing** -- a slug equal to a *different* workspace's id. This is the
   impersonation the old slug-first resolution allowed.
2. **UUID-shaped** -- any other slug in UUID shape. Slugs backfilled from the
   row's own id (``20260605_1000_add_workspace_slug``) are listed separately:
   they resolve to themselves and are harmless, but are not human handles.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from agentarea_common.config import get_database
from sqlalchemy import text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("check_workspace_slug_collisions")

_UUID_SHAPE = "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"


async def main() -> int:
    async with get_database().async_session_factory() as session:
        shadowing = (
            await session.execute(
                text(
                    "SELECT a.id, a.slug, a.owner_user_id FROM workspaces a "
                    "JOIN workspaces b ON a.slug = b.id AND a.id <> b.id"
                )
            )
        ).all()
        uuid_shaped = (
            await session.execute(
                text(
                    "SELECT id, slug, owner_user_id FROM workspaces "
                    "WHERE lower(slug) ~ :shape AND slug <> id"
                ),
                {"shape": _UUID_SHAPE},
            )
        ).all()
        self_named = (
            await session.execute(
                text("SELECT count(*) FROM workspaces WHERE slug = id AND lower(slug) ~ :shape"),
                {"shape": _UUID_SHAPE},
            )
        ).scalar_one()

    for row in shadowing:
        logger.error(
            "workspace %s (owner %s) has slug %r, the id of another workspace",
            row.id,
            row.owner_user_id,
            row.slug,
        )
    for row in uuid_shaped:
        if any(row.id == hit.id for hit in shadowing):
            continue
        logger.warning(
            "workspace %s (owner %s) has UUID-shaped slug %r", row.id, row.owner_user_id, row.slug
        )
    logger.info(
        "%d shadowing, %d other UUID-shaped, %d backfilled slug == id",
        len(shadowing),
        len(uuid_shaped),
        self_named,
    )
    return 1 if shadowing or uuid_shaped else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
