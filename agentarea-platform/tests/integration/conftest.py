"""Integration-test collection config.

Applies external-dependency gate markers by test-file name so the marks live
in one place instead of being sprinkled across ~20 modules. The core CI job
runs `-m "not requires_llm and not requires_docker and not requires_server and
not requires_s3 and not perf"`; a separate opt-in job runs the gated ones.
"""

import os
import time

# Normalize the process timezone to UTC for the test run. Some production
# code (e.g. agentarea_common.base.models.BaseModel's created_at default,
# which uses naive datetime.now()) mixes local-time and UTC naive datetimes
# with code that explicitly stamps datetime.utcnow() (e.g. the trigger
# repository's update_by_id). On a host whose local TZ is ahead of UTC this
# makes `updated_at` come out earlier than `created_at`, tripping the
# Trigger domain model's ordering validation. CI runners default to UTC so
# this never surfaces there; pin it here so local runs match that assumption
# instead of intermittently failing on developer machines in other zones.
os.environ.setdefault("TZ", "UTC")
if hasattr(time, "tzset"):
    time.tzset()

import pytest
import pytest_asyncio
from agentarea_common.base.models import BaseModel
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# Import ORM modules so their tables register on BaseModel.metadata before
# test_engine issues create_all() -- needed by root-level integration tests
# (trigger/task tests) that share this in-memory-SQLite db_session fixture.
from agentarea_agents.domain.models import Agent  # noqa: F401
from agentarea_llm.domain.models import ModelSpec, ProviderSpec  # noqa: F401
from agentarea_tasks.infrastructure.orm import TaskEventORM, TaskORM  # noqa: F401
from agentarea_triggers.infrastructure.orm import TriggerExecutionORM, TriggerORM  # noqa: F401


# SQLite foreign key support (mirrors tests/integration/repositories/conftest.py)
@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    if "sqlite" in str(dbapi_connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


@pytest_asyncio.fixture(scope="function")
async def test_engine():
    """Create a test database engine using in-memory SQLite."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    async with engine.begin() as conn:
        await conn.run_sync(BaseModel.metadata.create_all)

    yield engine

    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(test_engine):
    """Create a test database session with transaction rollback."""
    async_session = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        await session.begin()

        yield session

        await session.rollback()


# file stem (without .py) -> gate marker
_GATE_MARKERS: dict[str, str] = {
    # need a real LLM endpoint (Ollama/OpenRouter)
    "test_full_workflow_with_real_llm": "requires_llm",
    "test_real_llm_simple": "requires_llm",
    "test_real_llm_tool_calls": "requires_llm",
    "test_real_llm_with_mocked_db": "requires_llm",
    "test_real_completion_tool": "requires_llm",
    "test_malformed_llm_responses": "requires_llm",
    "test_react_framework_behavior": "requires_llm",
    "test_llm_response_parser": "requires_llm",
    "test_real_workflow_infrastructure": "requires_llm",
    "test_real_workflow_with_mocked_db": "requires_llm",
    "test_sdk_temporal_integration": "requires_llm",
    "test_a2a_task_execution_comprehensive": "requires_llm",
    # need object storage
    "test_artifact_service": "requires_s3",
    # need Docker / live MCP containers
    "test_mcp_containerization": "requires_docker",
    "test_mcp_real_integration": "requires_docker",
    "test_agent_mcp_e2e": "requires_docker",
    # need a running API server
    "test_e2e_main_flow": "requires_server",
    "test_protocol_endpoints": "requires_server",
    "test_a2a_real_api": "requires_server",
    "test_agent_delegation_e2e": "requires_server",
    # timing-sensitive stress test
    "test_trigger_performance_concurrent": "perf",
}


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Tag gated test files before pytest applies -m deselection."""
    for item in items:
        marker = _GATE_MARKERS.get(item.path.stem)
        if marker is not None:
            item.add_marker(getattr(pytest.mark, marker))
