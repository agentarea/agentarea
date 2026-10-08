"""A stream source holds a picked workspace secret by reference, against the real schema.

The reference is a ``secret_references`` row whose RESTRICT foreign key keeps
the secret from being deleted while the source resolves it; only the migrated
schema has that key. Set STREAMS_TEST_DATABASE_URL.
"""

import json
import os
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from agentarea_api.api.v1._stream_sources import create_webhook_source, release_webhook_source
from agentarea_common.auth.context import UserContext
from agentarea_common.base import RepositoryFactory
from agentarea_common.base.tenant_scope import workspace_scope
from agentarea_common.config.streams import EventStreamSettings
from agentarea_secrets.catalog_service import SecretCatalogService, SecretInUseError
from agentarea_secrets.database_secret_manager import DatabaseSecretManager
from agentarea_streams.application.stream_service import StreamService
from agentarea_streams.schemas import SecretRef, WebhookSourceCreate
from agentarea_triggers.channels.webhook_service import ChannelWebhookService
from agentarea_triggers.webhook_verification import resolve_signing_secret
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("STREAMS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="STREAMS_TEST_DATABASE_URL not set")

GRANT = "agentarea_common.base.workspace_scoped_repository.grant_resource_owner"


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
            secret = await catalog.create_user_secret("gh-hook", "the-value")
            service = StreamService(RepositoryFactory(session, ctx), EventStreamSettings())
            stream = await service.create_stream(name="github", description="", retention_days=7)
            await session.commit()

            source, issued = await create_webhook_source(
                stream.id,
                WebhookSourceCreate(
                    webhook_type="github",
                    credentials={"webhook_secret": SecretRef(secret_id=secret.id)},
                ),
                service=service,
                secret_manager=manager,
                secret_catalog=catalog,
                webhook_service=ChannelWebhookService("https://api.example"),
            )
            await session.commit()

            assert issued is None
            stream_id, source_id, secret_id = stream.id, source.id, secret.id
            stored = json.loads(await manager.get_secret(f"channel_cred:github:{source.id}"))
            assert stored == {"webhook_secret": {"secret_name": "gh-hook"}}
            assert await resolve_signing_secret("github", {}, None, manager, source.id) == (
                "the-value"
            )
            with pytest.raises(SecretInUseError):
                await catalog.delete_user_secret(secret_id)

            removed = await service.delete_source(stream_id, source_id)
            await release_webhook_source(
                removed,
                secret_manager=manager,
                secret_catalog=catalog,
                webhook_service=ChannelWebhookService("https://api.example"),
            )
            await session.commit()
            assert await manager.get_secret(f"channel_cred:github:{source_id}") is None
            await catalog.delete_user_secret(secret_id)
    await engine.dispose()
