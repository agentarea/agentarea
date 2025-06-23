"""
Simple integration tests for MCPServerRepository.

Tests all CRUD operations and business logic methods on the MCPServerRepository.
"""

from uuid import uuid4

import pytest
from agentarea_mcp.domain.models import MCPServer
from agentarea_mcp.infrastructure.repository import MCPServerRepository
from sqlalchemy.ext.asyncio import AsyncSession


class TestMCPServerRepository:
    """Test cases for MCPServerRepository."""

    def create_test_server(
        self,
        name: str = "Test MCP Server",
        description: str = "Test server description",
        docker_image_url: str = "test/mcp-server:latest",
        version: str = "1.0.0",
        tags: list = None,
        status: str = "active",
        is_public: bool = True,
        env_schema: list = None,
    ) -> MCPServer:
        """Create a test MCPServer with UUID objects."""
        if tags is None:
            tags = ["test", "development"]
        if env_schema is None:
            env_schema = []

        return MCPServer(
            id=uuid4(),
            name=name,
            description=description,
            docker_image_url=docker_image_url,
            version=version,
            tags=tags,
            status=status,
            is_public=is_public,
            env_schema=env_schema,
        )

    @pytest.mark.asyncio
    async def test_create_and_get_server(self, db_session: AsyncSession):
        """Test creating and retrieving an MCP server."""
        repository = MCPServerRepository(db_session)

        server = self.create_test_server(
            name="Test MCP Server",
            description="A test MCP server",
            docker_image_url="test/mcp:latest",
            version="1.0.0",
            tags=["test", "mcp"],
            status="active",
        )

        # Create server
        created_server = await repository.create(server)

        assert created_server is not None
        assert created_server.id == server.id
        assert created_server.name == "Test MCP Server"
        assert created_server.description == "A test MCP server"
        assert created_server.docker_image_url == "test/mcp:latest"
        assert created_server.version == "1.0.0"
        assert created_server.tags == ["test", "mcp"]
        assert created_server.status == "active"
        assert created_server.is_public is True

        # Retrieve server
        retrieved_server = await repository.get(created_server.id)

        assert retrieved_server is not None
        assert retrieved_server.id == created_server.id
        assert retrieved_server.name == "Test MCP Server"
        assert retrieved_server.status == "active"

    @pytest.mark.asyncio
    async def test_list_servers(self, db_session: AsyncSession):
        """Test listing MCP servers."""
        repository = MCPServerRepository(db_session)

        # Create multiple servers
        server1 = self.create_test_server(name="Server 1", status="active")
        server2 = self.create_test_server(name="Server 2", status="inactive")

        await repository.create(server1)
        await repository.create(server2)

        # List all servers
        servers = await repository.list()

        assert len(servers) >= 2
        server_names = [server.name for server in servers]
        assert "Server 1" in server_names
        assert "Server 2" in server_names

    @pytest.mark.asyncio
    async def test_update_server(self, db_session: AsyncSession):
        """Test updating an MCP server."""
        repository = MCPServerRepository(db_session)

        server = self.create_test_server(
            name="Original Server", description="Original description", status="inactive"
        )

        created_server = await repository.create(server)

        # Update the server
        created_server.name = "Updated Server"
        created_server.description = "Updated description"
        created_server.status = "active"

        updated_server = await repository.update(created_server)

        assert updated_server.name == "Updated Server"
        assert updated_server.description == "Updated description"
        assert updated_server.status == "active"

        # Verify the update persisted
        retrieved_server = await repository.get(created_server.id)
        assert retrieved_server.name == "Updated Server"
        assert retrieved_server.status == "active"

    @pytest.mark.asyncio
    async def test_delete_server(self, db_session: AsyncSession):
        """Test deleting an MCP server."""
        repository = MCPServerRepository(db_session)

        server = self.create_test_server(name="Server to Delete")
        created_server = await repository.create(server)

        # Delete the server
        delete_result = await repository.delete(created_server.id)
        assert delete_result is True

        # Verify it's deleted
        retrieved_server = await repository.get(created_server.id)
        assert retrieved_server is None

    @pytest.mark.asyncio
    async def test_get_nonexistent_server(self, db_session: AsyncSession):
        """Test retrieving a non-existent server returns None."""
        repository = MCPServerRepository(db_session)

        nonexistent_id = uuid4()
        result = await repository.get(nonexistent_id)

        assert result is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_server(self, db_session: AsyncSession):
        """Test deleting a non-existent server returns False."""
        repository = MCPServerRepository(db_session)

        nonexistent_id = uuid4()
        result = await repository.delete(nonexistent_id)

        assert result is False

    @pytest.mark.asyncio
    async def test_list_servers_by_status(self, db_session: AsyncSession):
        """Test filtering servers by status."""
        repository = MCPServerRepository(db_session)

        # Create servers with different statuses
        active_server = self.create_test_server(name="Active Server", status="active")
        inactive_server = self.create_test_server(name="Inactive Server", status="inactive")
        draft_server = self.create_test_server(name="Draft Server", status="draft")

        await repository.create(active_server)
        await repository.create(inactive_server)
        await repository.create(draft_server)

        # Filter by active status
        active_servers = await repository.list(status="active")
        active_names = [server.name for server in active_servers]
        assert "Active Server" in active_names
        assert "Inactive Server" not in active_names
        assert "Draft Server" not in active_names

    @pytest.mark.asyncio
    async def test_list_servers_by_public_status(self, db_session: AsyncSession):
        """Test filtering servers by public/private status."""
        repository = MCPServerRepository(db_session)

        # Create public and private servers
        public_server = self.create_test_server(name="Public Server", is_public=True)
        private_server = self.create_test_server(name="Private Server", is_public=False)

        await repository.create(public_server)
        await repository.create(private_server)

        # Filter by public servers
        public_servers = await repository.list(is_public=True)
        public_names = [server.name for server in public_servers]
        assert "Public Server" in public_names
        assert "Private Server" not in public_names

        # Filter by private servers
        private_servers = await repository.list(is_public=False)
        private_names = [server.name for server in private_servers]
        assert "Private Server" in private_names
        assert "Public Server" not in private_names

    @pytest.mark.asyncio
    async def test_list_servers_by_tag(self, db_session: AsyncSession):
        """Test filtering servers by tag."""
        repository = MCPServerRepository(db_session)

        # Create servers with different tags
        docker_server = self.create_test_server(name="Docker Server", tags=["docker", "container"])
        python_server = self.create_test_server(name="Python Server", tags=["python", "scripting"])
        mixed_server = self.create_test_server(
            name="Mixed Server", tags=["docker", "python", "utility"]
        )

        await repository.create(docker_server)
        await repository.create(python_server)
        await repository.create(mixed_server)

        # Filter by docker tag
        docker_servers = await repository.list(tag="docker")
        docker_names = [server.name for server in docker_servers]
        assert "Docker Server" in docker_names
        assert "Mixed Server" in docker_names
        assert "Python Server" not in docker_names

    @pytest.mark.asyncio
    async def test_complex_filtering(self, db_session: AsyncSession):
        """Test filtering servers with multiple criteria."""
        repository = MCPServerRepository(db_session)

        # Create various servers
        target_server = self.create_test_server(
            name="Target Server", status="active", is_public=True, tags=["production", "api"]
        )
        non_matching1 = self.create_test_server(
            name="Non-matching 1",
            status="inactive",  # Different status
            is_public=True,
            tags=["production", "api"],
        )
        non_matching2 = self.create_test_server(
            name="Non-matching 2",
            status="active",
            is_public=False,  # Different public status
            tags=["production", "api"],
        )
        non_matching3 = self.create_test_server(
            name="Non-matching 3",
            status="active",
            is_public=True,
            tags=["development", "test"],  # Different tags
        )

        await repository.create(target_server)
        await repository.create(non_matching1)
        await repository.create(non_matching2)
        await repository.create(non_matching3)

        # Filter with multiple criteria
        filtered_servers = await repository.list(status="active", is_public=True, tag="production")

        assert len(filtered_servers) == 1
        assert filtered_servers[0].name == "Target Server"

    @pytest.mark.asyncio
    async def test_server_versioning(self, db_session: AsyncSession):
        """Test servers with different versions."""
        repository = MCPServerRepository(db_session)

        # Create servers with different versions
        versions = ["1.0.0", "1.1.0", "2.0.0-beta", "latest"]

        for version in versions:
            server = self.create_test_server(name=f"Server {version}", version=version)

            created_server = await repository.create(server)
            assert created_server.version == version

            # Verify persistence
            retrieved_server = await repository.get(created_server.id)
            assert retrieved_server.version == version

    @pytest.mark.asyncio
    async def test_server_env_schema(self, db_session: AsyncSession):
        """Test servers with environment schema."""
        repository = MCPServerRepository(db_session)

        # Server with complex env schema
        env_schema = [
            {"name": "API_KEY", "type": "string", "required": True},
            {"name": "DEBUG", "type": "boolean", "default": False},
            {"name": "PORT", "type": "integer", "default": 8080},
        ]

        server = self.create_test_server(name="Env Schema Server", env_schema=env_schema)

        created_server = await repository.create(server)
        assert created_server.env_schema == env_schema

        # Verify persistence of complex JSON
        retrieved_server = await repository.get(created_server.id)
        assert retrieved_server.env_schema == env_schema
        assert len(retrieved_server.env_schema) == 3
        assert retrieved_server.env_schema[0]["name"] == "API_KEY"
