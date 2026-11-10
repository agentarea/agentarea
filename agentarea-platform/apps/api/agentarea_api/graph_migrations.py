"""Every graph migration, in id order; ``agentarea-api migrate`` applies the pending ones."""

from agentarea_common.rebac.graph_migrations import GraphMigration
from agentarea_secrets.graph_migrations import SECRET_OWNERS

GRAPH_MIGRATIONS: tuple[GraphMigration, ...] = (SECRET_OWNERS,)
