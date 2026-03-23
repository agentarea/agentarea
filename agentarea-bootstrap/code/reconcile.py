"""Async entrypoint for the IaC config reconciler."""

import asyncio
import logging
import os
import sys

logger = logging.getLogger(__name__)


async def run_reconciliation():
    """Run the reconciler against seed data directory."""
    from agentarea_common.config import get_database
    from agentarea_common.reconciler.service import ReconcilerService

    # Seed data paths — from env vars set by Helm chart
    config_dir = os.environ.get("SEED_DATA_DIR", "/seed-data")

    if not os.path.isdir(config_dir):
        logger.warning("Seed data directory not found: %s", config_dir)
        return

    db = get_database()
    reconciler = ReconcilerService(session_factory=db.async_session_factory)

    result = await reconciler.reconcile(config_dir)
    logger.info("Reconciliation result: %s", result)

    if result.errors:
        logger.error("Reconciliation had %d errors", len(result.errors))
        for entity_type, msg in result.errors:
            logger.error("  %s: %s", entity_type, msg)
        sys.exit(1)


def main():
    """Entrypoint for bootstrap reconciliation."""
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_reconciliation())


if __name__ == "__main__":
    main()
