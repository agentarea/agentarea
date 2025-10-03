"""Integration tests for workspace data isolation."""

import pytest

# Mark all async tests in this module
pytestmark = pytest.mark.asyncio
from uuid import uuid4

from agentarea_common.auth.context import UserContext
from agentarea_common.base.models import BaseModel, WorkspaceScopedMixin
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from sqlalchemy import String
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Mapped, mapped_column


class TestWorkspaceModel(BaseModel, WorkspaceScopedMixin):
    """Test model for workspace isolation testing."""

    __tablename__ = "test_workspace_isolation_model"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=True)
    category: Mapped[str] = mapped_column(String(100), nullable=True)


class TestWorkspaceModelRepository(WorkspaceScopedRepository[TestWorkspaceModel]):
    """Test repository for workspace isolation testing."""

    def __init__(self, session, user_context):
        super().__init__(session, TestWorkspaceModel, user_context)

    async def find_by_category(self, category: str, creator_scoped: bool = False):
        """Custom method to find by category."""
        return await self.find_by(creator_scoped=creator_scoped, category=category)


@pytest.fixture
async def test_engine():
    """Create test database engine."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(BaseModel.metadata.create_all)

    yield engine

    await engine.dispose()


@pytest.fixture
async def test_session_factory(test_engine):
    """Create test session factory."""
    return async_sessionmaker(test_engine, expire_on_commit=False)


@pytest.fixture
def user_contexts():
    """Create test user contexts for different workspaces and users."""
    return {
        "workspace1_user1": UserContext(user_id="user1", workspace_id="workspace1", roles=["user"]),
        "workspace1_user2": UserContext(user_id="user2", workspace_id="workspace1", roles=["user"]),
        "workspace2_user1": UserContext(user_id="user1", workspace_id="workspace2", roles=["user"]),
        "workspace2_user3": UserContext(user_id="user3", workspace_id="workspace2", roles=["user"]),
        "workspace3_admin": UserContext(
            user_id="admin", workspace_id="workspace3", roles=["admin"]
        ),
    }


class TestWorkspaceDataIsolation:
    """Integration tests for workspace data isolation."""

    async def test_complete_workspace_isolation(self, test_session_factory, user_contexts):
        """Test complete isolation between different workspaces."""
        async with test_session_factory() as session:
            # Create repositories for different workspaces
            repo_w1_u1 = TestWorkspaceModelRepository(session, user_contexts["workspace1_user1"])
            repo_w1_u2 = TestWorkspaceModelRepository(session, user_contexts["workspace1_user2"])
            repo_w2_u1 = TestWorkspaceModelRepository(session, user_contexts["workspace2_user1"])
            repo_w2_u3 = TestWorkspaceModelRepository(session, user_contexts["workspace2_user3"])
            repo_w3_admin = TestWorkspaceModelRepository(session, user_contexts["workspace3_admin"])

            # Create records in different workspaces
            record_w1_u1 = await repo_w1_u1.create(
                name="Record W1 U1", description="Created by user1 in workspace1", category="test"
            )
            record_w1_u2 = await repo_w1_u2.create(
                name="Record W1 U2", description="Created by user2 in workspace1", category="test"
            )
            record_w2_u1 = await repo_w2_u1.create(
                name="Record W2 U1", description="Created by user1 in workspace2", category="test"
            )
            record_w2_u3 = await repo_w2_u3.create(
                name="Record W2 U3", description="Created by user3 in workspace2", category="test"
            )
            record_w3_admin = await repo_w3_admin.create(
                name="Record W3 Admin",
                description="Created by admin in workspace3",
                category="admin",
            )

            # Test workspace1 isolation
            w1_records = await repo_w1_u1.list_all()
            assert len(w1_records) == 2  # Should see both records in workspace1
            w1_names = {r.name for r in w1_records}
            assert "Record W1 U1" in w1_names
            assert "Record W1 U2" in w1_names
            assert all(r.workspace_id == "workspace1" for r in w1_records)

            # Test workspace2 isolation
            w2_records = await repo_w2_u1.list_all()
            assert len(w2_records) == 2  # Should see both records in workspace2
            w2_names = {r.name for r in w2_records}
            assert "Record W2 U1" in w2_names
            assert "Record W2 U3" in w2_names
            assert all(r.workspace_id == "workspace2" for r in w2_records)

            # Test workspace3 isolation
            w3_records = await repo_w3_admin.list_all()
            assert len(w3_records) == 1  # Should only see admin record
            assert w3_records[0].name == "Record W3 Admin"
            assert w3_records[0].workspace_id == "workspace3"

            # Test cross-workspace access prevention
            # User in workspace1 should not see records from workspace2
            w1_cannot_see_w2 = await repo_w1_u1.get_by_id(record_w2_u1.id)
            assert w1_cannot_see_w2 is None

            # User in workspace2 should not see records from workspace1
            w2_cannot_see_w1 = await repo_w2_u1.get_by_id(record_w1_u1.id)
            assert w2_cannot_see_w1 is None

            # Admin in workspace3 should not see records from other workspaces
            w3_cannot_see_w1 = await repo_w3_admin.get_by_id(record_w1_u1.id)
            assert w3_cannot_see_w1 is None

    async def test_creator_scoped_vs_workspace_scoped_filtering(
        self, test_session_factory, user_contexts
    ):
        """Test the difference between creator-scoped and workspace-scoped filtering."""
        async with test_session_factory() as session:
            repo_u1 = TestWorkspaceModelRepository(session, user_contexts["workspace1_user1"])
            repo_u2 = TestWorkspaceModelRepository(session, user_contexts["workspace1_user2"])

            # Create records by different users in same workspace
            record_u1_1 = await repo_u1.create(name="User1 Record 1", category="shared")
            record_u1_2 = await repo_u1.create(name="User1 Record 2", category="private")
            record_u2_1 = await repo_u2.create(name="User2 Record 1", category="shared")
            record_u2_2 = await repo_u2.create(name="User2 Record 2", category="private")

            # Test workspace-scoped filtering (default behavior)
            u1_workspace_records = await repo_u1.list_all()
            assert len(u1_workspace_records) == 4  # Should see all workspace records

            u2_workspace_records = await repo_u2.list_all()
            assert len(u2_workspace_records) == 4  # Should see all workspace records

            # Test creator-scoped filtering
            u1_creator_records = await repo_u1.list_all(creator_scoped=True)
            assert len(u1_creator_records) == 2  # Should only see own records
            u1_names = {r.name for r in u1_creator_records}
            assert "User1 Record 1" in u1_names
            assert "User1 Record 2" in u1_names

            u2_creator_records = await repo_u2.list_all(creator_scoped=True)
            assert len(u2_creator_records) == 2  # Should only see own records
            u2_names = {r.name for r in u2_creator_records}
            assert "User2 Record 1" in u2_names
            assert "User2 Record 2" in u2_names

            # Test get_by_id with creator scoping
            # User1 can access any record in workspace (workspace-scoped)
            u1_can_access_u2_record = await repo_u1.get_by_id(record_u2_1.id)
            assert u1_can_access_u2_record is not None
            assert u1_can_access_u2_record.name == "User2 Record 1"

            # User1 cannot access user2's record with creator scoping
            u1_cannot_access_u2_creator = await repo_u1.get_by_id(
                record_u2_1.id, creator_scoped=True
            )
            assert u1_cannot_access_u2_creator is None

    async def test_workspace_isolation_with_custom_queries(
        self, test_session_factory, user_contexts
    ):
        """Test workspace isolation with custom repository methods."""
        async with test_session_factory() as session:
            repo_w1 = TestWorkspaceModelRepository(session, user_contexts["workspace1_user1"])
            repo_w2 = TestWorkspaceModelRepository(session, user_contexts["workspace2_user1"])

            # Create records with same category in different workspaces
            await repo_w1.create(name="W1 Category A", category="categoryA")
            await repo_w1.create(name="W1 Category B", category="categoryB")
            await repo_w2.create(name="W2 Category A", category="categoryA")
            await repo_w2.create(name="W2 Category B", category="categoryB")

            # Test custom query method respects workspace isolation
            w1_category_a = await repo_w1.find_by_category("categoryA")
            assert len(w1_category_a) == 1
            assert w1_category_a[0].name == "W1 Category A"
            assert w1_category_a[0].workspace_id == "workspace1"

            w2_category_a = await repo_w2.find_by_category("categoryA")
            assert len(w2_category_a) == 1
            assert w2_category_a[0].name == "W2 Category A"
            assert w2_category_a[0].workspace_id == "workspace2"

            # Test count with filters
            w1_count = await repo_w1.count(category="categoryA")
            assert w1_count == 1

            w2_count = await repo_w2.count(category="categoryA")
            assert w2_count == 1

    async def test_workspace_isolation_with_updates_and_deletes(
        self, test_session_factory, user_contexts
    ):
        """Test workspace isolation for update and delete operations."""
        async with test_session_factory() as session:
            repo_w1_u1 = TestWorkspaceModelRepository(session, user_contexts["workspace1_user1"])
            repo_w1_u2 = TestWorkspaceModelRepository(session, user_contexts["workspace1_user2"])
            repo_w2_u1 = TestWorkspaceModelRepository(session, user_contexts["workspace2_user1"])

            # Create records in different workspaces
            record_w1_u1 = await repo_w1_u1.create(name="W1 U1 Record", description="Original")
            record_w1_u2 = await repo_w1_u2.create(name="W1 U2 Record", description="Original")
            record_w2_u1 = await repo_w2_u1.create(name="W2 U1 Record", description="Original")

            # Test workspace-scoped updates
            # User1 in workspace1 can update any record in workspace1
            updated_u2_record = await repo_w1_u1.update(
                record_w1_u2.id, description="Updated by U1"
            )
            assert updated_u2_record is not None
            assert updated_u2_record.description == "Updated by U1"

            # User1 in workspace1 cannot update record in workspace2
            cannot_update_w2 = await repo_w1_u1.update(
                record_w2_u1.id, description="Should not work"
            )
            assert cannot_update_w2 is None

            # Test creator-scoped updates
            # User2 in workspace1 can only update their own record with creator scoping
            updated_own = await repo_w1_u2.update(
                record_w1_u2.id, creator_scoped=True, description="Updated by owner"
            )
            assert updated_own is not None
            assert updated_own.description == "Updated by owner"

            # User2 cannot update user1's record with creator scoping
            cannot_update_other = await repo_w1_u2.update(
                record_w1_u1.id, creator_scoped=True, description="Should not work"
            )
            assert cannot_update_other is None

            # Test workspace-scoped deletes
            # User1 in workspace1 can delete any record in workspace1
            deleted_u2_record = await repo_w1_u1.delete(record_w1_u2.id)
            assert deleted_u2_record is True

            # Verify record is deleted
            deleted_record = await repo_w1_u1.get_by_id(record_w1_u2.id)
            assert deleted_record is None

            # User1 in workspace1 cannot delete record in workspace2
            cannot_delete_w2 = await repo_w1_u1.delete(record_w2_u1.id)
            assert cannot_delete_w2 is False

            # Verify workspace2 record still exists
            w2_record_exists = await repo_w2_u1.get_by_id(record_w2_u1.id)
            assert w2_record_exists is not None

    async def test_repository_factory_workspace_isolation(
        self, test_session_factory, user_contexts
    ):
        """Test workspace isolation through repository factory."""
        async with test_session_factory() as session:
            # Create repository factories for different workspaces
            factory_w1 = RepositoryFactory(session, user_contexts["workspace1_user1"])
            factory_w2 = RepositoryFactory(session, user_contexts["workspace2_user1"])

            # Create repositories through factories
            repo_w1 = factory_w1.create_repository(TestWorkspaceModelRepository)
            repo_w2 = factory_w2.create_repository(TestWorkspaceModelRepository)

            # Verify repositories have correct context
            assert repo_w1.user_context.workspace_id == "workspace1"
            assert repo_w1.user_context.user_id == "user1"
            assert repo_w2.user_context.workspace_id == "workspace2"
            assert repo_w2.user_context.user_id == "user1"

            # Create records through factory-created repositories
            record_w1 = await repo_w1.create(name="Factory W1 Record")
            record_w2 = await repo_w2.create(name="Factory W2 Record")

            # Verify workspace isolation
            w1_records = await repo_w1.list_all()
            w2_records = await repo_w2.list_all()

            assert len(w1_records) == 1
            assert len(w2_records) == 1
            assert w1_records[0].workspace_id == "workspace1"
            assert w2_records[0].workspace_id == "workspace2"

            # Verify cross-workspace access prevention
            w1_cannot_see_w2 = await repo_w1.get_by_id(record_w2.id)
            w2_cannot_see_w1 = await repo_w2.get_by_id(record_w1.id)

            assert w1_cannot_see_w2 is None
            assert w2_cannot_see_w1 is None

    async def test_workspace_isolation_with_large_dataset(
        self, test_session_factory, user_contexts
    ):
        """Test workspace isolation with larger datasets and pagination."""
        async with test_session_factory() as session:
            repo_w1 = TestWorkspaceModelRepository(session, user_contexts["workspace1_user1"])
            repo_w2 = TestWorkspaceModelRepository(session, user_contexts["workspace2_user1"])

            # Create many records in each workspace
            w1_records = []
            w2_records = []

            for i in range(25):
                w1_record = await repo_w1.create(name=f"W1 Record {i:02d}", category="bulk_test")
                w1_records.append(w1_record)

                w2_record = await repo_w2.create(name=f"W2 Record {i:02d}", category="bulk_test")
                w2_records.append(w2_record)

            # Test pagination with workspace isolation
            w1_page1 = await repo_w1.list_all(limit=10, offset=0)
            w1_page2 = await repo_w1.list_all(limit=10, offset=10)
            w1_page3 = await repo_w1.list_all(limit=10, offset=20)

            assert len(w1_page1) == 10
            assert len(w1_page2) == 10
            assert len(w1_page3) == 5  # Remaining records

            # Verify all records belong to workspace1
            all_w1_pages = w1_page1 + w1_page2 + w1_page3
            assert all(r.workspace_id == "workspace1" for r in all_w1_pages)
            assert len(set(r.id for r in all_w1_pages)) == 25  # No duplicates

            # Test count with workspace isolation
            w1_count = await repo_w1.count()
            w2_count = await repo_w2.count()

            assert w1_count == 25
            assert w2_count == 25

            # Test filtered count
            w1_bulk_count = await repo_w1.count(category="bulk_test")
            w2_bulk_count = await repo_w2.count(category="bulk_test")

            assert w1_bulk_count == 25
            assert w2_bulk_count == 25

    async def test_workspace_isolation_edge_cases(self, test_session_factory, user_contexts):
        """Test edge cases for workspace isolation."""
        async with test_session_factory() as session:
            repo_w1 = TestWorkspaceModelRepository(session, user_contexts["workspace1_user1"])
            repo_w2 = TestWorkspaceModelRepository(session, user_contexts["workspace2_user1"])

            # Test with empty workspaces
            empty_w1 = await repo_w1.list_all()
            empty_w2 = await repo_w2.list_all()
            assert len(empty_w1) == 0
            assert len(empty_w2) == 0

            # Test count on empty workspaces
            count_w1 = await repo_w1.count()
            count_w2 = await repo_w2.count()
            assert count_w1 == 0
            assert count_w2 == 0

            # Test exists on non-existent records
            fake_id = uuid4()
            exists_w1 = await repo_w1.exists(fake_id)
            exists_w2 = await repo_w2.exists(fake_id)
            assert exists_w1 is False
            assert exists_w2 is False

            # Create one record and test edge cases
            record = await repo_w1.create(name="Edge Case Record")

            # Test find_one_by with no matches
            no_match = await repo_w1.find_one_by(name="Non-existent")
            assert no_match is None

            # Test find_one_by with match
            match = await repo_w1.find_one_by(name="Edge Case Record")
            assert match is not None
            assert match.id == record.id

            # Test cross-workspace find_one_by
            cross_workspace = await repo_w2.find_one_by(name="Edge Case Record")
            assert cross_workspace is None
