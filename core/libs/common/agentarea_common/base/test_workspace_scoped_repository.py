"""Test workspace-scoped repository functionality."""

import asyncio
from datetime import datetime
from uuid import uuid4

from sqlalchemy import String, DateTime
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from .models import BaseModel, WorkspaceScopedMixin
from .workspace_scoped_repository import WorkspaceScopedRepository
from ..auth.context import UserContext


class TestModel(BaseModel, WorkspaceScopedMixin):
    """Test model for workspace-scoped repository testing."""
    __tablename__ = "test_workspace_scoped_model"
    
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=True)


async def test_workspace_scoped_repository():
    """Test workspace-scoped repository functionality."""
    # Create in-memory SQLite database for testing
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=True)
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    
    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(BaseModel.metadata.create_all)
    
    # Create test user contexts
    user1_context = UserContext(user_id="user1", workspace_id="workspace1")
    user2_context = UserContext(user_id="user2", workspace_id="workspace1")  # Same workspace
    user3_context = UserContext(user_id="user3", workspace_id="workspace2")  # Different workspace
    
    async with async_session() as session:
        # Test basic repository
        repo1 = WorkspaceScopedRepository(session, TestModel, user1_context)
        repo2 = WorkspaceScopedRepository(session, TestModel, user2_context)
        repo3 = WorkspaceScopedRepository(session, TestModel, user3_context)
        
        print("=== Testing WorkspaceScopedRepository ===")
        
        # Create records
        print("\n1. Creating records...")
        record1 = await repo1.create(name="Record 1", description="Created by user1 in workspace1")
        record2 = await repo2.create(name="Record 2", description="Created by user2 in workspace1")
        record3 = await repo3.create(name="Record 3", description="Created by user3 in workspace2")
        
        print(f"Record 1: {record1.name} (created_by: {record1.created_by}, workspace_id: {record1.workspace_id})")
        print(f"Record 2: {record2.name} (created_by: {record2.created_by}, workspace_id: {record2.workspace_id})")
        print(f"Record 3: {record3.name} (created_by: {record3.created_by}, workspace_id: {record3.workspace_id})")
        
        # Test workspace isolation
        print("\n2. Testing workspace isolation...")
        
        # User1 should see both records in workspace1 (workspace-scoped, not user-scoped)
        workspace1_records = await repo1.list_all()
        print(f"User1 sees {len(workspace1_records)} records in workspace1:")
        for record in workspace1_records:
            print(f"  - {record.name} (created_by: {record.created_by})")
        
        # User2 should also see both records in workspace1
        workspace1_records_user2 = await repo2.list_all()
        print(f"User2 sees {len(workspace1_records_user2)} records in workspace1:")
        for record in workspace1_records_user2:
            print(f"  - {record.name} (created_by: {record.created_by})")
        
        # User3 should only see their record in workspace2
        workspace2_records = await repo3.list_all()
        print(f"User3 sees {len(workspace2_records)} records in workspace2:")
        for record in workspace2_records:
            print(f"  - {record.name} (created_by: {record.created_by})")
        
        # Test creator-scoped filtering
        print("\n3. Testing creator-scoped filtering...")
        
        # User1 should only see their own record when creator_scoped=True
        user1_records = await repo1.list_all(creator_scoped=True)
        print(f"User1 sees {len(user1_records)} records they created:")
        for record in user1_records:
            print(f"  - {record.name} (created_by: {record.created_by})")
        
        # User2 should only see their own record when creator_scoped=True
        user2_records = await repo2.list_all(creator_scoped=True)
        print(f"User2 sees {len(user2_records)} records they created:")
        for record in user2_records:
            print(f"  - {record.name} (created_by: {record.created_by})")
        
        # Test cross-workspace access prevention
        print("\n4. Testing cross-workspace access prevention...")
        
        # User3 should not be able to access records from workspace1
        try:
            record_from_other_workspace = await repo3.get_by_id(record1.id)
            if record_from_other_workspace is None:
                print("✓ Cross-workspace access correctly prevented")
            else:
                print("✗ Cross-workspace access not prevented!")
        except Exception as e:
            print(f"✓ Cross-workspace access prevented with exception: {e}")
        
        # Test update operations
        print("\n5. Testing update operations...")
        
        # User1 can update any record in their workspace (workspace-scoped)
        updated_record = await repo1.update(record2.id, description="Updated by user1")
        if updated_record:
            print(f"✓ User1 successfully updated record2: {updated_record.description}")
        else:
            print("✗ User1 could not update record2")
        
        # User1 can only update their own record when creator_scoped=True
        updated_own_record = await repo1.update(record1.id, creator_scoped=True, description="Updated by user1 (creator-scoped)")
        if updated_own_record:
            print(f"✓ User1 successfully updated their own record: {updated_own_record.description}")
        
        # User1 cannot update user2's record when creator_scoped=True
        cannot_update = await repo1.update(record2.id, creator_scoped=True, description="Should not work")
        if cannot_update is None:
            print("✓ User1 correctly cannot update user2's record with creator_scoped=True")
        else:
            print("✗ User1 incorrectly updated user2's record with creator_scoped=True")
        
        # Test count functionality
        print("\n6. Testing count functionality...")
        
        workspace1_count = await repo1.count()
        workspace1_user1_count = await repo1.count(creator_scoped=True)
        workspace2_count = await repo3.count()
        
        print(f"Workspace1 total records: {workspace1_count}")
        print(f"Workspace1 user1 records: {workspace1_user1_count}")
        print(f"Workspace2 total records: {workspace2_count}")
        
        print("\n=== Test completed ===")


if __name__ == "__main__":
    asyncio.run(test_workspace_scoped_repository())