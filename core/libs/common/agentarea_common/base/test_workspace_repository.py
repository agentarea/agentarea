"""Simple test to verify workspace-aware repository functionality."""

import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from .models import BaseModel, WorkspaceAwareMixin, SoftDeleteMixin
from .workspace_aware_repository import WorkspaceAwareRepository
from .soft_delete_repository import SoftDeleteRepository
from ..auth.context import UserContext


# Test models
class TestModel(BaseModel, WorkspaceAwareMixin):
    __tablename__ = "test_models"
    
    name: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[str] = mapped_column(String, nullable=True)


class TestSoftDeleteModel(BaseModel, WorkspaceAwareMixin, SoftDeleteMixin):
    __tablename__ = "test_soft_delete_models"
    
    name: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[str] = mapped_column(String, nullable=True)


async def test_workspace_repository():
    """Test workspace-aware repository functionality."""
    
    # Create in-memory SQLite database
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    
    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(BaseModel.metadata.create_all)
    
    # Test contexts
    user1_context = UserContext(user_id="user1", workspace_id="workspace1")
    user2_context = UserContext(user_id="user2", workspace_id="workspace1")  # Same workspace
    user3_context = UserContext(user_id="user3", workspace_id="workspace2")  # Different workspace
    
    async with async_session() as session:
        # Test basic repository
        repo1 = WorkspaceAwareRepository(session, TestModel, user1_context)
        repo2 = WorkspaceAwareRepository(session, TestModel, user2_context)
        repo3 = WorkspaceAwareRepository(session, TestModel, user3_context)
        
        print("=== Testing WorkspaceAwareRepository ===")
        
        # Create records
        record1 = await repo1.create(name="Record 1", value="Value 1")
        record2 = await repo2.create(name="Record 2", value="Value 2")
        record3 = await repo3.create(name="Record 3", value="Value 3")  # Different workspace
        
        print(f"Created records: {record1.id}, {record2.id}, {record3.id}")
        
        # Test workspace isolation
        workspace1_records = await repo1.list_all()
        workspace2_records = await repo3.list_all()
        
        print(f"Workspace 1 records: {len(workspace1_records)} (should be 2)")
        print(f"Workspace 2 records: {len(workspace2_records)} (should be 1)")
        
        # Test user scoping
        user1_records = await repo1.list_all(user_scoped=True)
        user2_records = await repo2.list_all(user_scoped=True)
        
        print(f"User 1 records: {len(user1_records)} (should be 1)")
        print(f"User 2 records: {len(user2_records)} (should be 1)")
        
        # Test get by ID with workspace isolation
        record1_from_repo1 = await repo1.get_by_id(record1.id)
        record1_from_repo3 = await repo3.get_by_id(record1.id)  # Different workspace
        
        print(f"Record 1 from same workspace: {record1_from_repo1 is not None} (should be True)")
        print(f"Record 1 from different workspace: {record1_from_repo3 is None} (should be True)")
        
        # Test soft delete repository
        print("\n=== Testing SoftDeleteRepository ===")
        
        soft_repo1 = SoftDeleteRepository(session, TestSoftDeleteModel, user1_context)
        soft_repo2 = SoftDeleteRepository(session, TestSoftDeleteModel, user2_context)
        
        # Create soft delete records
        soft_record1 = await soft_repo1.create(name="Soft Record 1", value="Soft Value 1")
        soft_record2 = await soft_repo2.create(name="Soft Record 2", value="Soft Value 2")
        
        print(f"Created soft delete records: {soft_record1.id}, {soft_record2.id}")
        
        # Test soft delete
        deleted = await soft_repo1.soft_delete(soft_record1.id)
        print(f"Soft deleted record 1: {deleted}")
        
        # Test list active vs deleted
        active_records = await soft_repo1.list_all()
        deleted_records = await soft_repo1.list_deleted()
        all_records = await soft_repo1.list_all(include_deleted=True)
        
        print(f"Active records: {len(active_records)} (should be 1)")
        print(f"Deleted records: {len(deleted_records)} (should be 1)")
        print(f"All records: {len(all_records)} (should be 2)")
        
        # Test restore
        restored = await soft_repo1.restore(soft_record1.id)
        print(f"Restored record 1: {restored}")
        
        active_after_restore = await soft_repo1.list_all()
        print(f"Active records after restore: {len(active_after_restore)} (should be 2)")
        
        print("\n=== All tests completed successfully! ===")


if __name__ == "__main__":
    asyncio.run(test_workspace_repository())