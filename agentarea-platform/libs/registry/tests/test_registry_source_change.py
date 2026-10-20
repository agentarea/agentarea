"""Moving a registry to another source reads the new one in full, after validating it."""

import pytest
import pytest_asyncio
from agentarea_registry.application.service import RegistryService
from agentarea_registry.domain.models import Registry
from agentarea_registry.infrastructure.repository import (
    RegistryItemRepository,
    RegistryRepository,
)


@pytest_asyncio.fixture
async def registry(db_session):
    record = Registry(
        name="acme",
        registry_type="skills",
        source_type="url",
        source_url="https://old.example/skills.json",
    )
    record.source_etag = '"v1"'
    db_session.add(record)
    await db_session.commit()
    return record


def _service(db_session) -> RegistryService:
    return RegistryService(
        RegistryRepository(db_session), RegistryItemRepository(db_session), server_repo=None
    )


async def test_a_new_source_type_clears_the_etag(db_session, registry):
    updated = await _service(db_session).update_registry(
        registry.id, source_type="github", source_url="acme/skills", source_ref="main"
    )

    assert (updated.source_type, updated.source_url, updated.source_ref) == (
        "github",
        "acme/skills",
        "main",
    )
    assert updated.source_etag is None


async def test_a_new_source_type_is_validated_with_its_url(db_session, registry):
    with pytest.raises(ValueError, match="owner/repo"):
        await _service(db_session).update_registry(registry.id, source_type="github")
    with pytest.raises(ValueError, match="source_type must be one of"):
        await _service(db_session).update_registry(registry.id, source_type="ftp")
