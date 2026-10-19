"""A stream source holds a picked workspace secret by reference, against the real schema.

The reference is a ``secret_references`` row whose RESTRICT foreign key keeps
the secret from being deleted while the source resolves it; only the migrated
schema has that key. Set STREAMS_TEST_DATABASE_URL.
"""

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from agentarea_api.api.v1._stream_sources import create_source, release_source
from agentarea_common.auth.context import UserContext
from agentarea_common.base import RepositoryFactory
from agentarea_common.base.tenant_scope import workspace_scope
from agentarea_common.config.streams import EventStreamSettings
from agentarea_secrets.catalog_service import SecretCatalogService, SecretInUseError
from agentarea_secrets.database_secret_manager import DatabaseSecretManager
from agentarea_streams.application.source_credentials import read_source_credentials
from agentarea_streams.application.stream_service import StreamService
from agentarea_streams.schemas import SecretRef, SourceCreate
from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("STREAMS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="STREAMS_TEST_DATABASE_URL not set")

GRANT = "agentarea_common.base.workspace_scoped_repository.grant_resource_owner"
CATALOG = Path(__file__).resolve().parents[4] / "data" / "catalog" / "source-types.json"


async def _ensure_source_type(session: AsyncSession, slug: str) -> None:
    """The catalog row a source of ``slug`` is read by, as the registry sync writes it."""
    found = await session.execute(
        text(
            "SELECT 1 FROM registry_items WHERE registry_type = 'source_types' "
            "AND external_id = :slug AND registry_active"
        ),
        {"slug": slug},
    )
    if found.first() is not None:
        return
    entry = next(e for e in json.loads(CATALOG.read_text())["source_types"] if e["slug"] == slug)
    registry_id = str(uuid4())
    await session.execute(
        text(
            "INSERT INTO registries (id, name, registry_type, source_type, source_url, "
            "is_active, created_at, updated_at) "
            "VALUES (:id, :name, 'source_types', 'managed', 'x', true, now(), now())"
        ),
        {"id": registry_id, "name": f"test-{registry_id}"},
    )
    await session.execute(
        text(
            "INSERT INTO registry_items (id, registry_id, external_id, name, spec, tags, "
            "sort_key, featured, registry_type, registry_priority, registry_active, "
            "created_at, updated_at) "
            "SELECT :id, r.id, :slug, :slug, CAST(:spec AS jsonb), '[]'::jsonb, :slug, false, "
            "r.registry_type, r.recommendation_priority, r.is_active, now(), now() "
            "FROM registries r WHERE r.id = :registry_id"
        ),
        {"id": str(uuid4()), "registry_id": registry_id, "slug": slug, "spec": json.dumps(entry)},
    )


async def test_a_picked_secret_is_resolved_at_use_and_cannot_be_deleted_while_in_use():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    ctx = UserContext(user_id="u", workspace_id=str(uuid4()))
    async with maker() as session:
        with workspace_scope(ctx.workspace_id), patch(GRANT, new=AsyncMock()):
            manager = DatabaseSecretManager(
                session=session, user_context=ctx, encryption_key=Fernet.generate_key().decode()
            )
            catalog = SecretCatalogService(session, ctx, manager)
            await _ensure_source_type(session, "github")
            secret = await catalog.create_user_secret("gh-hook", "the-value")
            service = StreamService(RepositoryFactory(session, ctx), EventStreamSettings())
            stream = await service.create_stream(name="github", description="")
            await session.commit()

            source, issued = await create_source(
                stream.id,
                SourceCreate(
                    source_type="github",
                    credentials={"webhook_secret": SecretRef(secret_id=secret.id)},
                ),
                service=service,
                secret_manager=manager,
                secret_catalog=catalog,
            )
            await session.commit()

            assert issued == {}
            stream_id, source_id, secret_id = stream.id, source.id, secret.id
            stored = json.loads(await manager.get_secret(f"channel_cred:github:{source.id}"))
            assert stored == {"webhook_secret": {"secret_name": "gh-hook"}}
            assert await read_source_credentials(manager, "github", source.credential_key) == {
                "webhook_secret": "the-value"
            }
            with pytest.raises(SecretInUseError):
                await catalog.delete_user_secret(secret_id)

            removed = await service.delete_source(stream_id, source_id)
            await release_source(removed, secret_manager=manager, secret_catalog=catalog)
            await session.commit()
            assert await manager.get_secret(f"channel_cred:github:{source_id}") is None
            await catalog.delete_user_secret(secret_id)
    await engine.dispose()
