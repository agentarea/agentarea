from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance
from agentarea_mcp.infrastructure.repository import MCPServerInstanceRepository
from sqlalchemy.ext.asyncio import AsyncSession


class TestMCPServerInstanceRepository:
    """Test suite for MCPServerInstanceRepository integration tests."""

    @pytest.fixture
    def user_context(self):
        """Create a test user context."""
        return UserContext(
            user_id="test-user-123", workspace_id="test-workspace-456", roles=["user"]
        )

    def create_test_instance(
        self,
        name: str = "Test Instance",
        description: str = "Test description",
        server_spec_id: str = "test_spec_id",
        json_spec: dict = None,
        status: str = "active",
        workspace_id: str = "test-workspace-456",
        created_by: str = "test-user-123",
    ) -> MCPServerInstance:
        """Helper to create test MCPServerInstance with UUID objects."""
        return MCPServerInstance(
            name=name,
            description=description,
            server_spec_id=server_spec_id,
            json_spec=json_spec or {"env_vars": ["API_KEY", "SECRET_TOKEN"]},
            status=status,
            workspace_id=workspace_id,
            created_by=created_by,
        )

    @pytest.mark.asyncio
    async def test_create_and_get_instance(
        self, db_session: AsyncSession, user_context: UserContext
    ):
        """Test creating and retrieving an MCP server instance."""
        repository = MCPServerInstanceRepository(db_session, user_context)

        # Create instance using the new workspace-scoped create method
        created_instance = await repository.create(
            name="OpenAI MCP Server",
            description="OpenAI integration server",
            server_spec_id="openai_spec_v1",
            json_spec={"env_vars": ["OPENAI_API_KEY"], "config": {"model": "gpt-4"}},
            status="active",
        )

        # Verify creation
        assert created_instance.id is not None
        assert created_instance.name == "OpenAI MCP Server"
        assert created_instance.description == "OpenAI integration server"
        assert created_instance.server_spec_id == "openai_spec_v1"
        assert created_instance.json_spec == {
            "env_vars": ["OPENAI_API_KEY"],
            "config": {"model": "gpt-4"},
        }
        assert created_instance.status == "active"
        assert created_instance.workspace_id == user_context.workspace_id
        assert created_instance.created_by == user_context.user_id
        assert created_instance.created_at is not None
        assert created_instance.updated_at is not None

        # Retrieve the instance
        retrieved_instance = await repository.get_by_id(created_instance.id)

        assert retrieved_instance is not None
        assert retrieved_instance.id == created_instance.id
        assert retrieved_instance.name == "OpenAI MCP Server"
        assert retrieved_instance.json_spec["env_vars"] == ["OPENAI_API_KEY"]

    @pytest.mark.asyncio
    async def test_list_instances(self, db_session: AsyncSession, user_context: UserContext):
        """Test listing MCP server instances."""
        repository = MCPServerInstanceRepository(db_session, user_context)

        # Create multiple instances using the new workspace-scoped create method
        await repository.create(
            name="GitHub MCP Server", description="GitHub integration", status="active"
        )
        await repository.create(
            name="Slack MCP Server", description="Slack integration", status="inactive"
        )
        await repository.create(
            name="Database MCP Server", description="Database connector", status="pending"
        )

        # List all instances
        all_instances = await repository.list_all()

        assert len(all_instances) >= 3
        instance_names = [instance.name for instance in all_instances]
        assert "GitHub MCP Server" in instance_names
        assert "Slack MCP Server" in instance_names
        assert "Database MCP Server" in instance_names

    @pytest.mark.asyncio
    async def test_update_instance(self, db_session: AsyncSession, user_context: UserContext):
        """Test updating an existing MCP server instance."""
        repository = MCPServerInstanceRepository(db_session, user_context)

        # Create instance using the new workspace-scoped create method
        created_instance = await repository.create(
            name="Original Server",
            description="Original description",
            status="pending",
            json_spec={"env_vars": ["OLD_KEY"]},
        )

        # Update the instance using the new workspace-scoped update method
        updated_instance = await repository.update(
            created_instance.id,
            name="Updated Server",
            description="Updated description",
            status="active",
            json_spec={"env_vars": ["NEW_KEY", "ANOTHER_KEY"], "updated": True},
        )

        assert updated_instance.name == "Updated Server"
        assert updated_instance.description == "Updated description"
        assert updated_instance.status == "active"
        assert updated_instance.json_spec["env_vars"] == ["NEW_KEY", "ANOTHER_KEY"]
        assert updated_instance.json_spec["updated"] is True

        # Verify the update persisted
        retrieved_instance = await repository.get_by_id(created_instance.id)
        assert retrieved_instance.name == "Updated Server"
        assert retrieved_instance.status == "active"
        assert retrieved_instance.json_spec["updated"] is True

    @pytest.mark.asyncio
    async def test_delete_instance(self, db_session: AsyncSession, user_context: UserContext):
        """Test deleting an MCP server instance."""
        repository = MCPServerInstanceRepository(db_session, user_context)

        # Create instance using the new workspace-scoped create method
        created_instance = await repository.create(
            name="Temporary Server", description="Will be deleted"
        )

        # Delete the instance
        delete_result = await repository.delete(created_instance.id)
        assert delete_result is True

        # Verify it's deleted
        retrieved_instance = await repository.get_by_id(created_instance.id)
        assert retrieved_instance is None

    @pytest.mark.asyncio
    async def test_get_nonexistent_instance(
        self, db_session: AsyncSession, user_context: UserContext
    ):
        """Test retrieving a non-existent instance returns None."""
        repository = MCPServerInstanceRepository(db_session, user_context)

        nonexistent_id = uuid4()
        result = await repository.get_by_id(nonexistent_id)

        assert result is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_instance(
        self, db_session: AsyncSession, user_context: UserContext
    ):
        """Test deleting a non-existent instance returns False."""
        repository = MCPServerInstanceRepository(db_session, user_context)

        nonexistent_id = uuid4()
        result = await repository.delete(nonexistent_id)

        assert result is False

    @pytest.mark.asyncio
    async def test_list_instances_by_status(
        self, db_session: AsyncSession, user_context: UserContext
    ):
        """Test filtering instances by status."""
        repository = MCPServerInstanceRepository(db_session, user_context)

        # Create instances with different statuses using the new workspace-scoped create method
        await repository.create(name="Active Server", status="active")
        await repository.create(name="Pending Server", status="pending")
        await repository.create(name="Inactive Server", status="inactive")

        # Filter by active status using the new method
        active_instances = await repository.list_by_status("active")
        active_names = [instance.name for instance in active_instances]
        assert "Active Server" in active_names
        assert "Pending Server" not in active_names
        assert "Inactive Server" not in active_names

    @pytest.mark.asyncio
    async def test_list_instances_by_server_spec_id(
        self, db_session: AsyncSession, user_context: UserContext
    ):
        """Test filtering instances by server_spec_id."""
        repository = MCPServerInstanceRepository(db_session, user_context)

        # Create instances with different server_spec_ids using the new workspace-scoped create method
        await repository.create(name="OpenAI Server 1", server_spec_id="openai_v1")
        await repository.create(name="OpenAI Server 2", server_spec_id="openai_v1")
        await repository.create(name="GitHub Server", server_spec_id="github_v1")

        # Filter by openai_v1 spec using the new method
        openai_instances = await repository.list_by_server_spec("openai_v1")

        assert len(openai_instances) == 2
        instance_names = [instance.name for instance in openai_instances]
        assert "OpenAI Server 1" in instance_names
        assert "OpenAI Server 2" in instance_names
        assert "GitHub Server" not in instance_names

    @pytest.mark.asyncio
    async def test_complex_filtering(self, db_session: AsyncSession, user_context: UserContext):
        """Test filtering instances with multiple criteria."""
        repository = MCPServerInstanceRepository(db_session, user_context)

        # Create various instances using the new workspace-scoped create method
        await repository.create(name="Target Server", server_spec_id="target_spec", status="active")
        await repository.create(
            name="Non-matching 1",
            server_spec_id="target_spec",
            status="inactive",  # Different status
        )
        await repository.create(
            name="Non-matching 2",
            server_spec_id="other_spec",  # Different spec
            status="active",
        )

        # Filter with multiple criteria using the new list_all method
        filtered_instances = await repository.list_all(
            server_spec_id="target_spec", status="active"
        )

        assert len(filtered_instances) == 1
        assert filtered_instances[0].name == "Target Server"

    @pytest.mark.asyncio
    async def test_json_spec_operations(self, db_session: AsyncSession, user_context: UserContext):
        """Test JSON spec field operations."""
        repository = MCPServerInstanceRepository(db_session, user_context)

        # Create instance with complex JSON spec using the new workspace-scoped create method
        complex_json_spec = {
            "env_vars": ["API_KEY", "SECRET_TOKEN", "DATABASE_URL"],
            "config": {"timeout": 30, "retry_count": 3, "features": ["feature_a", "feature_b"]},
            "metadata": {"version": "1.2.3", "author": "AgentArea Team"},
        }

        created_instance = await repository.create(
            name="JSON Test Server", json_spec=complex_json_spec
        )

        # Verify JSON spec is stored and retrieved correctly
        retrieved_instance = await repository.get_by_id(created_instance.id)

        assert retrieved_instance.json_spec["env_vars"] == [
            "API_KEY",
            "SECRET_TOKEN",
            "DATABASE_URL",
        ]
        assert retrieved_instance.json_spec["config"]["timeout"] == 30
        assert retrieved_instance.json_spec["config"]["features"] == ["feature_a", "feature_b"]
        assert retrieved_instance.json_spec["metadata"]["version"] == "1.2.3"

        # Test the helper method
        env_vars = retrieved_instance.get_configured_env_vars()
        assert env_vars == ["API_KEY", "SECRET_TOKEN", "DATABASE_URL"]
