"""Test repository factory functionality."""

import asyncio
from datetime import datetime
from uuid import uuid4

from sqlalchemy import String, DateTime
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from agentarea_common.base.models import BaseModel, WorkspaceScopedMixin
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.auth.context import UserContext


class TestModel(BaseModel, WorkspaceScopedMixin):
    """Test model for repository factory testing."""
    __tablename__ = "test_factory_model"
    
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=True)


class TestModelRepository(WorkspaceScopedRepository[TestModel]):
    """Test repository for factory testing."""
    
    def __init__(self, session, user_context):
        super().__init__(session, TestModel, user_context)
    
    async def find_by_name(self, name: str):
        """Custom method to find by name."""
        return await self.find_one_by(name=name)


async def test_repository_factory():
    """Test repository factory functionality."""
    # Create in-memory SQLite database for testing
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=True)
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    
    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(BaseModel.metadata.create_all)
    
    # Create test user contexts
    user1_context = UserContext(user_id="user1", workspace_id="workspace1")
    user2_context = UserContext(user_id="user2", workspace_id="workspace2")
    
    async with async_session() as session:
        print("=== Testing RepositoryFactory ===")
        
        # Create repository factories
        factory1 = RepositoryFactory(session, user1_context)
        factory2 = RepositoryFactory(session, user2_context)
        
        print("\n1. Creating repositories via factory...")
        
        # Create repositories using the factory
        repo1 = factory1.create_repository(TestModelRepository)
        repo2 = factory2.create_repository(TestModelRepository)
        
        print(f"Repository 1 user context: {repo1.user_context.user_id}, {repo1.user_context.workspace_id}")
        print(f"Repository 2 user context: {repo2.user_context.user_id}, {repo2.user_context.workspace_id}")
        
        # Verify repositories have correct context
        assert repo1.user_context.user_id == "user1"
        assert repo1.user_context.workspace_id == "workspace1"
        assert repo2.user_context.user_id == "user2"
        assert repo2.user_context.workspace_id == "workspace2"
        
        print("✓ Repositories created with correct user context")
        
        print("\n2. Testing repository functionality via factory...")
        
        # Create records using factory-created repositories
        record1 = await repo1.create(name="Record 1", description="Created via factory repo1")
        record2 = await repo2.create(name="Record 2", description="Created via factory repo2")
        
        print(f"Record 1: {record1.name} (workspace: {record1.workspace_id}, created_by: {record1.created_by})")
        print(f"Record 2: {record2.name} (workspace: {record2.workspace_id}, created_by: {record2.created_by})")
        
        # Verify workspace isolation
        repo1_records = await repo1.list_all()
        repo2_records = await repo2.list_all()
        
        print(f"Repo1 sees {len(repo1_records)} records")
        print(f"Repo2 sees {len(repo2_records)} records")
        
        assert len(repo1_records) == 1
        assert len(repo2_records) == 1
        assert repo1_records[0].workspace_id == "workspace1"
        assert repo2_records[0].workspace_id == "workspace2"
        
        print("✓ Workspace isolation working correctly")
        
        print("\n3. Testing custom repository methods...")
        
        # Test custom method
        found_record = await repo1.find_by_name("Record 1")
        assert found_record is not None
        assert found_record.name == "Record 1"
        
        # Should not find record from other workspace
        not_found = await repo1.find_by_name("Record 2")
        assert not_found is None
        
        print("✓ Custom repository methods working correctly")
        
        print("\n4. Testing multiple repository creation...")
        
        # Create multiple repositories of the same type
        repo1_alt = factory1.create_repository(TestModelRepository)
        
        # Should have same context
        assert repo1_alt.user_context.user_id == repo1.user_context.user_id
        assert repo1_alt.user_context.workspace_id == repo1.user_context.workspace_id
        
        # Should see same data
        alt_records = await repo1_alt.list_all()
        assert len(alt_records) == 1
        assert alt_records[0].id == record1.id
        
        print("✓ Multiple repository instances work correctly")
        
        print("\n=== Repository Factory Test completed ===")


if __name__ == "__main__":
    asyncio.run(test_repository_factory())