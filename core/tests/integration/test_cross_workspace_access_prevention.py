"""Integration tests for cross-workspace access prevention."""

import pytest

# Mark all async tests in this module
pytestmark = pytest.mark.asyncio
from agentarea_common.auth.context import UserContext
from agentarea_common.base.models import BaseModel, WorkspaceScopedMixin
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from sqlalchemy import String
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Mapped, mapped_column


class CrossWorkspaceTestModel(BaseModel, WorkspaceScopedMixin):
    """Test model for cross-workspace access prevention testing."""

    __tablename__ = "cross_workspace_test_model"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sensitive_data: Mapped[str] = mapped_column(String(500), nullable=True)
    category: Mapped[str] = mapped_column(String(100), nullable=True)


class CrossWorkspaceTestRepository(WorkspaceScopedRepository[CrossWorkspaceTestModel]):
    """Test repository for cross-workspace access prevention."""

    def __init__(self, session, user_context):
        super().__init__(session, CrossWorkspaceTestModel, user_context)


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
def workspace_contexts():
    """Create test contexts for different workspaces and users."""
    return {
        # Company A workspaces
        "company_a_dev": UserContext(
            user_id="dev1", workspace_id="company-a-dev", roles=["developer"]
        ),
        "company_a_prod": UserContext(
            user_id="dev1", workspace_id="company-a-prod", roles=["developer"]
        ),
        "company_a_admin": UserContext(
            user_id="admin1", workspace_id="company-a-dev", roles=["admin"]
        ),
        # Company B workspaces
        "company_b_dev": UserContext(
            user_id="dev2", workspace_id="company-b-dev", roles=["developer"]
        ),
        "company_b_prod": UserContext(
            user_id="dev2", workspace_id="company-b-prod", roles=["developer"]
        ),
        "company_b_admin": UserContext(
            user_id="admin2", workspace_id="company-b-dev", roles=["admin"]
        ),
        # Shared service workspace
        "shared_service": UserContext(
            user_id="service", workspace_id="shared-service", roles=["service"]
        ),
        # Malicious user trying to access other workspaces
        "malicious_user": UserContext(
            user_id="hacker", workspace_id="hacker-workspace", roles=["user"]
        ),
    }


class TestCrossWorkspaceAccessPrevention:
    """Test suite for preventing cross-workspace access."""

    async def test_complete_workspace_isolation_between_companies(
        self, test_session_factory, workspace_contexts
    ):
        """Test complete isolation between different company workspaces."""
        async with test_session_factory() as session:
            # Create repositories for different companies
            repo_company_a = CrossWorkspaceTestRepository(
                session, workspace_contexts["company_a_dev"]
            )
            repo_company_b = CrossWorkspaceTestRepository(
                session, workspace_contexts["company_b_dev"]
            )
            repo_malicious = CrossWorkspaceTestRepository(
                session, workspace_contexts["malicious_user"]
            )

            # Create sensitive data in each company's workspace
            company_a_secret = await repo_company_a.create(
                name="Company A Secret",
                sensitive_data="Company A's confidential information",
                category="confidential",
            )

            company_b_secret = await repo_company_b.create(
                name="Company B Secret",
                sensitive_data="Company B's confidential information",
                category="confidential",
            )

            # Test that Company A cannot access Company B's data
            company_a_cannot_see_b = await repo_company_a.get_by_id(company_b_secret.id)
            assert company_a_cannot_see_b is None

            # Test that Company B cannot access Company A's data
            company_b_cannot_see_a = await repo_company_b.get_by_id(company_a_secret.id)
            assert company_b_cannot_see_a is None

            # Test that malicious user cannot access either company's data
            malicious_cannot_see_a = await repo_malicious.get_by_id(company_a_secret.id)
            malicious_cannot_see_b = await repo_malicious.get_by_id(company_b_secret.id)
            assert malicious_cannot_see_a is None
            assert malicious_cannot_see_b is None

            # Test list operations don't leak data
            company_a_list = await repo_company_a.list_all()
            company_b_list = await repo_company_b.list_all()
            malicious_list = await repo_malicious.list_all()

            assert len(company_a_list) == 1
            assert len(company_b_list) == 1
            assert len(malicious_list) == 0

            assert company_a_list[0].name == "Company A Secret"
            assert company_b_list[0].name == "Company B Secret"

    async def test_cross_workspace_update_prevention(
        self, test_session_factory, workspace_contexts
    ):
        """Test that users cannot update records in other workspaces."""
        async with test_session_factory() as session:
            repo_company_a = CrossWorkspaceTestRepository(
                session, workspace_contexts["company_a_dev"]
            )
            repo_company_b = CrossWorkspaceTestRepository(
                session, workspace_contexts["company_b_dev"]
            )
            repo_malicious = CrossWorkspaceTestRepository(
                session, workspace_contexts["malicious_user"]
            )

            # Create records in each workspace
            company_a_record = await repo_company_a.create(
                name="Company A Record", sensitive_data="Original A data"
            )

            company_b_record = await repo_company_b.create(
                name="Company B Record", sensitive_data="Original B data"
            )

            # Test that Company A cannot update Company B's record
            company_a_cannot_update_b = await repo_company_a.update(
                company_b_record.id, sensitive_data="Hacked by Company A"
            )
            assert company_a_cannot_update_b is None

            # Test that Company B cannot update Company A's record
            company_b_cannot_update_a = await repo_company_b.update(
                company_a_record.id, sensitive_data="Hacked by Company B"
            )
            assert company_b_cannot_update_a is None

            # Test that malicious user cannot update any records
            malicious_cannot_update_a = await repo_malicious.update(
                company_a_record.id, sensitive_data="Hacked by malicious user"
            )
            malicious_cannot_update_b = await repo_malicious.update(
                company_b_record.id, sensitive_data="Hacked by malicious user"
            )
            assert malicious_cannot_update_a is None
            assert malicious_cannot_update_b is None

            # Verify original data is unchanged
            original_a = await repo_company_a.get_by_id(company_a_record.id)
            original_b = await repo_company_b.get_by_id(company_b_record.id)

            assert original_a.sensitive_data == "Original A data"
            assert original_b.sensitive_data == "Original B data"

    async def test_cross_workspace_delete_prevention(
        self, test_session_factory, workspace_contexts
    ):
        """Test that users cannot delete records in other workspaces."""
        async with test_session_factory() as session:
            repo_company_a = CrossWorkspaceTestRepository(
                session, workspace_contexts["company_a_dev"]
            )
            repo_company_b = CrossWorkspaceTestRepository(
                session, workspace_contexts["company_b_dev"]
            )
            repo_malicious = CrossWorkspaceTestRepository(
                session, workspace_contexts["malicious_user"]
            )

            # Create records in each workspace
            company_a_record = await repo_company_a.create(name="Company A Record")
            company_b_record = await repo_company_b.create(name="Company B Record")

            # Test that Company A cannot delete Company B's record
            company_a_cannot_delete_b = await repo_company_a.delete(company_b_record.id)
            assert company_a_cannot_delete_b is False

            # Test that Company B cannot delete Company A's record
            company_b_cannot_delete_a = await repo_company_b.delete(company_a_record.id)
            assert company_b_cannot_delete_a is False

            # Test that malicious user cannot delete any records
            malicious_cannot_delete_a = await repo_malicious.delete(company_a_record.id)
            malicious_cannot_delete_b = await repo_malicious.delete(company_b_record.id)
            assert malicious_cannot_delete_a is False
            assert malicious_cannot_delete_b is False

            # Verify records still exist in their respective workspaces
            a_still_exists = await repo_company_a.get_by_id(company_a_record.id)
            b_still_exists = await repo_company_b.get_by_id(company_b_record.id)

            assert a_still_exists is not None
            assert b_still_exists is not None

    async def test_cross_workspace_search_and_filter_isolation(
        self, test_session_factory, workspace_contexts
    ):
        """Test that search and filter operations don't leak data across workspaces."""
        async with test_session_factory() as session:
            repo_company_a = CrossWorkspaceTestRepository(
                session, workspace_contexts["company_a_dev"]
            )
            repo_company_b = CrossWorkspaceTestRepository(
                session, workspace_contexts["company_b_dev"]
            )

            # Create records with same names/categories in different workspaces
            await repo_company_a.create(name="Shared Name", category="shared_category")
            await repo_company_a.create(name="Company A Unique", category="shared_category")

            await repo_company_b.create(name="Shared Name", category="shared_category")
            await repo_company_b.create(name="Company B Unique", category="shared_category")

            # Test find_by operations
            company_a_shared_name = await repo_company_a.find_by(name="Shared Name")
            company_b_shared_name = await repo_company_b.find_by(name="Shared Name")

            assert len(company_a_shared_name) == 1
            assert len(company_b_shared_name) == 1
            assert company_a_shared_name[0].workspace_id == "company-a-dev"
            assert company_b_shared_name[0].workspace_id == "company-b-dev"

            # Test find_by with category filter
            company_a_category = await repo_company_a.find_by(category="shared_category")
            company_b_category = await repo_company_b.find_by(category="shared_category")

            assert len(company_a_category) == 2
            assert len(company_b_category) == 2
            assert all(r.workspace_id == "company-a-dev" for r in company_a_category)
            assert all(r.workspace_id == "company-b-dev" for r in company_b_category)

            # Test find_one_by operations
            company_a_unique = await repo_company_a.find_one_by(name="Company B Unique")
            company_b_unique = await repo_company_b.find_one_by(name="Company A Unique")

            assert company_a_unique is None  # Cannot find Company B's record
            assert company_b_unique is None  # Cannot find Company A's record

    async def test_cross_workspace_count_isolation(self, test_session_factory, workspace_contexts):
        """Test that count operations are isolated by workspace."""
        async with test_session_factory() as session:
            repo_company_a = CrossWorkspaceTestRepository(
                session, workspace_contexts["company_a_dev"]
            )
            repo_company_b = CrossWorkspaceTestRepository(
                session, workspace_contexts["company_b_dev"]
            )
            repo_malicious = CrossWorkspaceTestRepository(
                session, workspace_contexts["malicious_user"]
            )

            # Create different numbers of records in each workspace
            for i in range(5):
                await repo_company_a.create(name=f"Company A Record {i}", category="test")

            for i in range(3):
                await repo_company_b.create(name=f"Company B Record {i}", category="test")

            # Test count operations
            company_a_count = await repo_company_a.count()
            company_b_count = await repo_company_b.count()
            malicious_count = await repo_malicious.count()

            assert company_a_count == 5
            assert company_b_count == 3
            assert malicious_count == 0

            # Test count with filters
            company_a_test_count = await repo_company_a.count(category="test")
            company_b_test_count = await repo_company_b.count(category="test")

            assert company_a_test_count == 5
            assert company_b_test_count == 3

    async def test_cross_workspace_exists_isolation(self, test_session_factory, workspace_contexts):
        """Test that exists operations are isolated by workspace."""
        async with test_session_factory() as session:
            repo_company_a = CrossWorkspaceTestRepository(
                session, workspace_contexts["company_a_dev"]
            )
            repo_company_b = CrossWorkspaceTestRepository(
                session, workspace_contexts["company_b_dev"]
            )

            # Create record in Company A
            company_a_record = await repo_company_a.create(name="Company A Record")

            # Test exists operations
            exists_in_a = await repo_company_a.exists(company_a_record.id)
            exists_in_b = await repo_company_b.exists(company_a_record.id)

            assert exists_in_a is True
            assert exists_in_b is False  # Should not exist in Company B's workspace

    async def test_admin_users_cannot_cross_workspace_boundaries(
        self, test_session_factory, workspace_contexts
    ):
        """Test that even admin users cannot access other workspaces."""
        async with test_session_factory() as session:
            repo_company_a_admin = CrossWorkspaceTestRepository(
                session, workspace_contexts["company_a_admin"]
            )
            repo_company_b_admin = CrossWorkspaceTestRepository(
                session, workspace_contexts["company_b_admin"]
            )

            # Create sensitive record in Company B
            company_b_secret = await repo_company_b_admin.create(
                name="Company B Admin Secret", sensitive_data="Top secret Company B data"
            )

            # Test that Company A admin cannot access Company B's data
            company_a_admin_cannot_see = await repo_company_a_admin.get_by_id(company_b_secret.id)
            assert company_a_admin_cannot_see is None

            # Test that Company A admin cannot update Company B's data
            company_a_admin_cannot_update = await repo_company_a_admin.update(
                company_b_secret.id, sensitive_data="Hacked by Company A admin"
            )
            assert company_a_admin_cannot_update is None

            # Test that Company A admin cannot delete Company B's data
            company_a_admin_cannot_delete = await repo_company_a_admin.delete(company_b_secret.id)
            assert company_a_admin_cannot_delete is False

    async def test_same_user_different_workspaces_isolation(
        self, test_session_factory, workspace_contexts
    ):
        """Test isolation when same user operates in different workspaces."""
        async with test_session_factory() as session:
            # Same user (dev1) in different workspaces
            repo_dev_workspace = CrossWorkspaceTestRepository(
                session, workspace_contexts["company_a_dev"]
            )
            repo_prod_workspace = CrossWorkspaceTestRepository(
                session, workspace_contexts["company_a_prod"]
            )

            # Create records in each workspace
            dev_record = await repo_dev_workspace.create(
                name="Development Record", sensitive_data="Dev environment data"
            )

            prod_record = await repo_prod_workspace.create(
                name="Production Record", sensitive_data="Production environment data"
            )

            # Test that dev workspace cannot see prod data
            dev_cannot_see_prod = await repo_dev_workspace.get_by_id(prod_record.id)
            assert dev_cannot_see_prod is None

            # Test that prod workspace cannot see dev data
            prod_cannot_see_dev = await repo_prod_workspace.get_by_id(dev_record.id)
            assert prod_cannot_see_dev is None

            # Test list operations
            dev_list = await repo_dev_workspace.list_all()
            prod_list = await repo_prod_workspace.list_all()

            assert len(dev_list) == 1
            assert len(prod_list) == 1
            assert dev_list[0].name == "Development Record"
            assert prod_list[0].name == "Production Record"

    async def test_workspace_isolation_with_or_raise_methods(
        self, test_session_factory, workspace_contexts
    ):
        """Test that *_or_raise methods properly handle cross-workspace access."""
        async with test_session_factory() as session:
            repo_company_a = CrossWorkspaceTestRepository(
                session, workspace_contexts["company_a_dev"]
            )
            repo_company_b = CrossWorkspaceTestRepository(
                session, workspace_contexts["company_b_dev"]
            )

            # Create record in Company A
            company_a_record = await repo_company_a.create(name="Company A Record")

            # Test get_by_id_or_raise from different workspace
            with pytest.raises(NoResultFound, match="not found in workspace"):
                await repo_company_b.get_by_id_or_raise(company_a_record.id)

            # Test update_or_raise from different workspace
            with pytest.raises(NoResultFound, match="not found in workspace"):
                await repo_company_b.update_or_raise(company_a_record.id, name="Hacked")

            # Test delete_or_raise from different workspace
            with pytest.raises(NoResultFound, match="not found in workspace"):
                await repo_company_b.delete_or_raise(company_a_record.id)

    async def test_workspace_isolation_stress_test(self, test_session_factory, workspace_contexts):
        """Stress test workspace isolation with many records and operations."""
        async with test_session_factory() as session:
            repo_company_a = CrossWorkspaceTestRepository(
                session, workspace_contexts["company_a_dev"]
            )
            repo_company_b = CrossWorkspaceTestRepository(
                session, workspace_contexts["company_b_dev"]
            )
            repo_malicious = CrossWorkspaceTestRepository(
                session, workspace_contexts["malicious_user"]
            )

            # Create many records in each workspace
            company_a_records = []
            company_b_records = []

            for i in range(50):
                a_record = await repo_company_a.create(
                    name=f"Company A Record {i:03d}", category=f"category_{i % 5}"
                )
                company_a_records.append(a_record)

                b_record = await repo_company_b.create(
                    name=f"Company B Record {i:03d}", category=f"category_{i % 5}"
                )
                company_b_records.append(b_record)

            # Test that each workspace only sees its own records
            a_list = await repo_company_a.list_all()
            b_list = await repo_company_b.list_all()
            malicious_list = await repo_malicious.list_all()

            assert len(a_list) == 50
            assert len(b_list) == 50
            assert len(malicious_list) == 0

            # Test random access attempts across workspaces
            import random

            for _ in range(20):
                # Pick random records from each workspace
                a_record = random.choice(company_a_records)
                b_record = random.choice(company_b_records)

                # Test cross-workspace access fails
                assert await repo_company_a.get_by_id(b_record.id) is None
                assert await repo_company_b.get_by_id(a_record.id) is None
                assert await repo_malicious.get_by_id(a_record.id) is None
                assert await repo_malicious.get_by_id(b_record.id) is None

            # Test bulk operations don't leak data
            a_category_0 = await repo_company_a.find_by(category="category_0")
            b_category_0 = await repo_company_b.find_by(category="category_0")

            assert len(a_category_0) == 10  # Records 0, 5, 10, ..., 45
            assert len(b_category_0) == 10
            assert all(r.workspace_id == "company-a-dev" for r in a_category_0)
            assert all(r.workspace_id == "company-b-dev" for r in b_category_0)

    async def test_workspace_isolation_with_pagination(
        self, test_session_factory, workspace_contexts
    ):
        """Test workspace isolation with paginated queries."""
        async with test_session_factory() as session:
            repo_company_a = CrossWorkspaceTestRepository(
                session, workspace_contexts["company_a_dev"]
            )
            repo_company_b = CrossWorkspaceTestRepository(
                session, workspace_contexts["company_b_dev"]
            )

            # Create records in both workspaces
            for i in range(25):
                await repo_company_a.create(name=f"A-{i:02d}")
                await repo_company_b.create(name=f"B-{i:02d}")

            # Test paginated queries maintain workspace isolation
            a_page1 = await repo_company_a.list_all(limit=10, offset=0)
            a_page2 = await repo_company_a.list_all(limit=10, offset=10)
            a_page3 = await repo_company_a.list_all(limit=10, offset=20)

            b_page1 = await repo_company_b.list_all(limit=10, offset=0)
            b_page2 = await repo_company_b.list_all(limit=10, offset=10)
            b_page3 = await repo_company_b.list_all(limit=10, offset=20)

            # Verify page sizes
            assert len(a_page1) == 10
            assert len(a_page2) == 10
            assert len(a_page3) == 5
            assert len(b_page1) == 10
            assert len(b_page2) == 10
            assert len(b_page3) == 5

            # Verify workspace isolation in all pages
            all_a_records = a_page1 + a_page2 + a_page3
            all_b_records = b_page1 + b_page2 + b_page3

            assert all(r.workspace_id == "company-a-dev" for r in all_a_records)
            assert all(r.workspace_id == "company-b-dev" for r in all_b_records)

            # Verify no overlap in record IDs
            a_ids = {r.id for r in all_a_records}
            b_ids = {r.id for r in all_b_records}
            assert len(a_ids.intersection(b_ids)) == 0
