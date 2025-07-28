"""
Global pytest configuration and fixtures
========================================

Shared fixtures and configuration for all tests.
"""

import asyncio
import os
import sys
import uuid
from uuid import uuid4
from datetime import datetime

import pytest
import pytest_asyncio
from agentarea_common.base.models import BaseModel
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.test_utils import create_test_user_context
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_llm.domain.models import ModelSpec, ProviderSpec, ProviderConfig, ModelInstance
from sqlalchemy import event, select
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# Add the core directory to Python path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def test_redis_available():
    """Check if Redis is available for tests."""
    try:
        import redis
        r = redis.Redis.from_url("redis://localhost:6379")
        r.ping()
        return True
    except (ImportError, redis.ConnectionError, redis.TimeoutError):
        pytest.skip("Redis not available for testing")


@pytest.fixture
def test_postgres_available():
    """Check if PostgreSQL is available for tests."""
    try:
        import asyncpg
        import asyncio
        
        async def check_postgres():
            try:
                conn = await asyncpg.connect(
                    host="localhost",
                    port=5432,
                    user="postgres",
                    password="postgres",
                    database="aiagents"
                )
                await conn.close()
                return True
            except Exception:
                return False
        
        if not asyncio.run(check_postgres()):
            pytest.skip("PostgreSQL not available for testing")
    except ImportError:
        pytest.skip("asyncpg not available for testing")


@pytest.fixture
def test_temporal_available():
    """Check if Temporal is available for tests."""
    import socket
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(("localhost", 7233))
        sock.close()
        if result != 0:
            pytest.skip("Temporal not available for testing")
    except Exception:
        pytest.skip("Temporal not available for testing")


@pytest.fixture
def mock_agent_config():
    """Mock agent configuration"""
    return {
        "id": str(uuid4()),
        "name": "Test Agent",
        "description": "Test agent for unit tests",
        "instruction": "You are a helpful test assistant",
        "planning_enabled": False,
        "workflow_type": "single",
        "tools_config": {"mcp_servers": [], "builtin_tools": [], "custom_tools": []},
    }


@pytest.fixture
def test_user_context():
    """Create a test user context for workspace-scoped tests."""
    return create_test_user_context(
        user_id="test-user-123",
        workspace_id="test-workspace-456",
        roles=["user"]
    )


@pytest.fixture
def test_user_context_2():
    """Create a second test user context for isolation testing."""
    return create_test_user_context(
        user_id="test-user-789",
        workspace_id="test-workspace-456",  # Same workspace
        roles=["user"]
    )


@pytest.fixture
def test_user_context_different_workspace():
    """Create a test user context in a different workspace for isolation testing."""
    return create_test_user_context(
        user_id="test-user-999",
        workspace_id="different-workspace-999",
        roles=["user"]
    )


@pytest.fixture
def admin_user_context():
    """Create an admin user context for testing admin functionality."""
    return create_test_user_context(
        user_id="admin-user-123",
        workspace_id="admin-workspace-456",
        roles=["user", "admin"]
    )


@pytest.fixture
def repository_factory(db_session, test_user_context):
    """Create a repository factory with test user context."""
    return RepositoryFactory(db_session, test_user_context)


# Integration test markers
pytest_plugins = []


def pytest_configure(config):
    """Configure pytest with custom markers"""
    config.addinivalue_line(
        "markers", "integration: mark test as integration test requiring real services"
    )
    config.addinivalue_line("markers", "slow: mark test as slow running")
    config.addinivalue_line("markers", "unit: mark test as unit test (isolated)")


def pytest_collection_modifyitems(config, items):
    """Modify collected test items to add markers based on file location"""
    for item in items:
        # Add marker based on test file location
        if "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
        elif "unit" in str(item.fspath):
            item.add_marker(pytest.mark.unit)

        # Mark slow tests
        if "slow" in item.name.lower():
            item.add_marker(pytest.mark.slow)


# Enable foreign key constraints for SQLite
@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if "sqlite" in str(dbapi_connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """Create a test database engine using in-memory SQLite for the session."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
        echo=False,
    )

    # Create all tables
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


@pytest_asyncio.fixture(scope="function")
async def populated_db_session(test_engine):
    """Fixture that provides a database session populated with test data for the new 4-entity architecture."""
    async with AsyncSession(test_engine) as session:
        # Check if provider already exists
        existing_provider = await session.execute(
            select(ProviderSpec).where(ProviderSpec.provider_key == "ollama")
        )
        provider_spec = existing_provider.scalar_one_or_none()
        
        if provider_spec is None:
            # Create Ollama provider spec with proper UUID object
            provider_spec = ProviderSpec(
                id=uuid.UUID("183a5efc-2525-4a1e-aded-1a5d5e9ff13b"),
                provider_key="ollama",
                name="Ollama",
                description="Local and open source models through Ollama",
                provider_type="ollama_chat",
                icon="ollama",
                is_builtin=True,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            session.add(provider_spec)
        
        await session.flush()
        
        # Check and create model specs for various Ollama models
        qwen_spec = await session.execute(
            select(ModelSpec).where(ModelSpec.model_name == "qwen2.5", ModelSpec.provider_spec_id == provider_spec.id)
        )
        if qwen_spec.scalar_one_or_none() is None:
            qwen_model_spec = ModelSpec(
                id=uuid.UUID("a1b2c3d4-e5f6-7890-1234-567890abcdef"),
                provider_spec_id=provider_spec.id,
                model_name="qwen2.5",
                display_name="Qwen 2.5",
                description="Qwen 2.5 model for general tasks",
                context_window=8192,
                is_active=True,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            session.add(qwen_model_spec)
        
        llama_spec = await session.execute(
            select(ModelSpec).where(ModelSpec.model_name == "llama2", ModelSpec.provider_spec_id == provider_spec.id)
        )
        if llama_spec.scalar_one_or_none() is None:
            llama_model_spec = ModelSpec(
                id=uuid.UUID("b2c3d4e5-f6a7-8901-2345-678901bcdef0"),
                provider_spec_id=provider_spec.id,
                model_name="llama2",
                display_name="Llama 2",
                description="Llama 2 model",
                context_window=4096,
                is_active=True,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            session.add(llama_model_spec)
        
        mistral_spec = await session.execute(
            select(ModelSpec).where(ModelSpec.model_name == "mistral", ModelSpec.provider_spec_id == provider_spec.id)
        )
        if mistral_spec.scalar_one_or_none() is None:
            mistral_model_spec = ModelSpec(
                id=uuid.UUID("c3d4e5f6-a7b8-9012-3456-789012cdef01"),
                provider_spec_id=provider_spec.id,
                model_name="mistral",
                display_name="Mistral",
                description="Mistral model",
                context_window=8192,
                is_active=True,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            session.add(mistral_model_spec)
        
        await session.flush()
        
        # Check and create provider config
        existing_config = await session.execute(
            select(ProviderConfig).where(ProviderConfig.name == "Local Ollama")
        )
        provider_config = existing_config.scalar_one_or_none()
        
        if provider_config is None:
            provider_config = ProviderConfig(
                id=uuid.UUID("f1e2d3c4-b5a6-9708-1234-567890fedcba"),
                provider_spec_id=provider_spec.id,
                name="Local Ollama",
                api_key="dummy_key_for_ollama",
                endpoint_url="http://localhost:11434",
                user_id=None,
                is_active=True,
                is_public=True,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            session.add(provider_config)
        
        await session.flush()
        
        # Check and create model instances
        qwen_instance = await session.execute(
            select(ModelInstance).where(ModelInstance.name == "Qwen 2.5 Local")
        )
        if qwen_instance.scalar_one_or_none() is None:
            qwen_model_instance = ModelInstance(
                id=uuid.UUID("11111111-2222-3333-4444-555555555555"),
                provider_config_id=provider_config.id,
                model_spec_id=uuid.UUID("a1b2c3d4-e5f6-7890-1234-567890abcdef"),
                name="Qwen 2.5 Local",
                description="Local Qwen 2.5 instance",
                is_active=True,
                is_public=True,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            session.add(qwen_model_instance)
        
        llama_instance = await session.execute(
            select(ModelInstance).where(ModelInstance.name == "Llama 2 Local")
        )
        if llama_instance.scalar_one_or_none() is None:
            llama_model_instance = ModelInstance(
                id=uuid.UUID("22222222-3333-4444-5555-666666666666"),
                provider_config_id=provider_config.id,
                model_spec_id=uuid.UUID("b2c3d4e5-f6a7-8901-2345-678901bcdef0"),
                name="Llama 2 Local",
                description="Local Llama 2 instance",
                is_active=True,
                is_public=True,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            session.add(llama_model_instance)
        
        await session.commit()
        
        yield session
