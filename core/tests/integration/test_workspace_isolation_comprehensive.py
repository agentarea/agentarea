"""Comprehensive integration tests for complete workspace isolation system."""

import pytest

# Mark all async tests in this module
pytestmark = pytest.mark.asyncio
from unittest.mock import MagicMock

from agentarea_common.auth.context import UserContext
from agentarea_common.auth.jwt_handler import JWTTokenHandler
from agentarea_common.auth.test_utils import generate_test_jwt_token
from agentarea_common.base.models import BaseModel, WorkspaceScopedMixin
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from fastapi import Request
from sqlalchemy import String
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Mapped, mapped_column


class ComprehensiveTestModel(BaseModel, WorkspaceScopedMixin):
    """Comprehensive test model for full workspace isolation testing."""

    __tablename__ = "comprehensive_test_model"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=True)
    category: Mapped[str] = mapped_column(String(100), nullable=True)
    priority: Mapped[int] = mapped_column(nullable=True, default=1)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)


class ComprehensiveTestRepository(WorkspaceScopedRepository[ComprehensiveTestModel]):
    """Comprehensive test repository."""

    def __init__(self, session, user_context):
        super().__init__(session, ComprehensiveTestModel, user_context)

    async def find_active_by_category(self, category: str, creator_scoped: bool = False):
        """Custom method to find active records by category."""
        return await self.find_by(creator_scoped=creator_scoped, category=category, is_active=True)

    async def get_high_priority_count(self, creator_scoped: bool = False):
        """Custom method to count high priority records."""
        return await self.count(creator_scoped=creator_scoped, priority=3)


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
def comprehensive_contexts():
    """Create comprehensive test contexts for various scenarios."""
    return {
        # Enterprise A - Multiple departments
        "enterprise_a_hr": UserContext(
            user_id="hr_manager", workspace_id="enterprise-a-hr", roles=["manager"]
        ),
        "enterprise_a_hr_emp": UserContext(
            user_id="hr_employee", workspace_id="enterprise-a-hr", roles=["employee"]
        ),
        "enterprise_a_finance": UserContext(
            user_id="finance_manager", workspace_id="enterprise-a-finance", roles=["manager"]
        ),
        "enterprise_a_it": UserContext(
            user_id="it_admin", workspace_id="enterprise-a-it", roles=["admin"]
        ),
        # Enterprise B - Competitor company
        "enterprise_b_hr": UserContext(
            user_id="hr_manager_b", workspace_id="enterprise-b-hr", roles=["manager"]
        ),
        "enterprise_b_finance": UserContext(
            user_id="finance_manager_b", workspace_id="enterprise-b-finance", roles=["manager"]
        ),
        # Startup C - Small company
        "startup_c_main": UserContext(
            user_id="founder", workspace_id="startup-c-main", roles=["owner"]
        ),
        "startup_c_dev": UserContext(
            user_id="developer", workspace_id="startup-c-main", roles=["developer"]
        ),
        # Government Agency
        "gov_agency_public": UserContext(
            user_id="public_officer", workspace_id="gov-agency-public", roles=["officer"]
        ),
        "gov_agency_classified": UserContext(
            user_id="classified_officer",
            workspace_id="gov-agency-classified",
            roles=["officer", "classified"],
        ),
        # Malicious actors
        "external_attacker": UserContext(
            user_id="attacker", workspace_id="attacker-workspace", roles=["user"]
        ),
        "insider_threat": UserContext(
            user_id="insider", workspace_id="compromised-workspace", roles=["user"]
        ),
    }


class TestComprehensiveWorkspaceIsolation:
    """Comprehensive test suite for complete workspace isolation."""

    async def test_end_to_end_jwt_to_repository_isolation(
        self, test_session_factory, comprehensive_contexts
    ):
        """Test complete end-to-end isolation from JWT token to repository operations."""
        async with test_session_factory() as session:
            jwt_handler = JWTTokenHandler(secret_key="test-secret", algorithm="HS256")

            # Create JWT tokens for different workspaces
            hr_token = generate_test_jwt_token(
                user_id="hr_manager",
                workspace_id="enterprise-a-hr",
                roles=["manager"],
                secret_key="test-secret",
            )

            finance_token = generate_test_jwt_token(
                user_id="finance_manager",
                workspace_id="enterprise-a-finance",
                roles=["manager"],
                secret_key="test-secret",
            )

            # Create mock requests with JWT tokens
            hr_request = MagicMock(spec=Request)
            hr_request.headers = {"authorization": f"Bearer {hr_token}"}

            finance_request = MagicMock(spec=Request)
            finance_request.headers = {"authorization": f"Bearer {finance_token}"}

            # Extract user contexts from JWT tokens
            hr_context = await jwt_handler.extract_user_context(hr_request)
            finance_context = await jwt_handler.extract_user_context(finance_request)

            # Create repositories with extracted contexts
            hr_repo = ComprehensiveTestRepository(session, hr_context)
            finance_repo = ComprehensiveTestRepository(session, finance_context)

            # Create sensitive data in each workspace
            hr_record = await hr_repo.create(
                name="Employee Salary Data",
                description="Confidential salary information",
                category="confidential",
                priority=3,
            )

            finance_record = await finance_repo.create(
                name="Financial Projections",
                description="Q4 financial projections",
                category="confidential",
                priority=3,
            )

            # Verify complete isolation
            assert hr_record.workspace_id == "enterprise-a-hr"
            assert finance_record.workspace_id == "enterprise-a-finance"

            # Test cross-workspace access prevention
            hr_cannot_see_finance = await hr_repo.get_by_id(finance_record.id)
            finance_cannot_see_hr = await finance_repo.get_by_id(hr_record.id)

            assert hr_cannot_see_finance is None
            assert finance_cannot_see_hr is None

            # Test custom repository methods maintain isolation
            hr_confidential = await hr_repo.find_active_by_category("confidential")
            finance_confidential = await finance_repo.find_active_by_category("confidential")

            assert len(hr_confidential) == 1
            assert len(finance_confidential) == 1
            assert hr_confidential[0].name == "Employee Salary Data"
            assert finance_confidential[0].name == "Financial Projections"

            # Test count methods maintain isolation
            hr_high_priority = await hr_repo.get_high_priority_count()
            finance_high_priority = await finance_repo.get_high_priority_count()

            assert hr_high_priority == 1
            assert finance_high_priority == 1

    async def test_multi_tenant_enterprise_isolation(
        self, test_session_factory, comprehensive_contexts
    ):
        """Test isolation between multiple enterprise tenants."""
        async with test_session_factory() as session:
            # Create repositories for different enterprises
            ent_a_hr_repo = ComprehensiveTestRepository(
                session, comprehensive_contexts["enterprise_a_hr"]
            )
            ent_a_finance_repo = ComprehensiveTestRepository(
                session, comprehensive_contexts["enterprise_a_finance"]
            )
            ent_b_hr_repo = ComprehensiveTestRepository(
                session, comprehensive_contexts["enterprise_b_hr"]
            )
            ent_b_finance_repo = ComprehensiveTestRepository(
                session, comprehensive_contexts["enterprise_b_finance"]
            )

            # Create data in each enterprise workspace
            await ent_a_hr_repo.create(name="Enterprise A HR Data", category="hr")
            await ent_a_finance_repo.create(name="Enterprise A Finance Data", category="finance")
            await ent_b_hr_repo.create(name="Enterprise B HR Data", category="hr")
            await ent_b_finance_repo.create(name="Enterprise B Finance Data", category="finance")

            # Test complete isolation between enterprises
            ent_a_hr_records = await ent_a_hr_repo.list_all()
            ent_a_finance_records = await ent_a_finance_repo.list_all()
            ent_b_hr_records = await ent_b_hr_repo.list_all()
            ent_b_finance_records = await ent_b_finance_repo.list_all()

            # Each workspace should only see its own data
            assert len(ent_a_hr_records) == 1
            assert len(ent_a_finance_records) == 1
            assert len(ent_b_hr_records) == 1
            assert len(ent_b_finance_records) == 1

            # Verify workspace IDs
            assert ent_a_hr_records[0].workspace_id == "enterprise-a-hr"
            assert ent_a_finance_records[0].workspace_id == "enterprise-a-finance"
            assert ent_b_hr_records[0].workspace_id == "enterprise-b-hr"
            assert ent_b_finance_records[0].workspace_id == "enterprise-b-finance"

            # Test that enterprises cannot access each other's data
            ent_a_hr_count = await ent_a_hr_repo.count()
            ent_b_hr_count = await ent_b_hr_repo.count()

            assert ent_a_hr_count == 1  # Only sees own data
            assert ent_b_hr_count == 1  # Only sees own data

    async def test_government_classified_workspace_isolation(
        self, test_session_factory, comprehensive_contexts
    ):
        """Test isolation for government classified vs public workspaces."""
        async with test_session_factory() as session:
            public_repo = ComprehensiveTestRepository(
                session, comprehensive_contexts["gov_agency_public"]
            )
            classified_repo = ComprehensiveTestRepository(
                session, comprehensive_contexts["gov_agency_classified"]
            )

            # Create public and classified data
            public_record = await public_repo.create(
                name="Public Information",
                description="Publicly available government data",
                category="public",
            )

            classified_record = await classified_repo.create(
                name="Classified Information",
                description="Top secret government data",
                category="classified",
            )

            # Test that public workspace cannot access classified data
            public_cannot_see_classified = await public_repo.get_by_id(classified_record.id)
            assert public_cannot_see_classified is None

            # Test that classified workspace cannot access public data
            classified_cannot_see_public = await classified_repo.get_by_id(public_record.id)
            assert classified_cannot_see_public is None

            # Test list operations maintain strict isolation
            public_list = await public_repo.list_all()
            classified_list = await classified_repo.list_all()

            assert len(public_list) == 1
            assert len(classified_list) == 1
            assert public_list[0].category == "public"
            assert classified_list[0].category == "classified"

    async def test_startup_vs_enterprise_isolation(
        self, test_session_factory, comprehensive_contexts
    ):
        """Test isolation between startup and enterprise workspaces."""
        async with test_session_factory() as session:
            startup_repo = ComprehensiveTestRepository(
                session, comprehensive_contexts["startup_c_main"]
            )
            enterprise_repo = ComprehensiveTestRepository(
                session, comprehensive_contexts["enterprise_a_hr"]
            )

            # Create startup and enterprise data
            startup_record = await startup_repo.create(
                name="Startup Innovation",
                description="Innovative startup product",
                category="innovation",
            )

            enterprise_record = await enterprise_repo.create(
                name="Enterprise Process",
                description="Established enterprise process",
                category="process",
            )

            # Test complete isolation
            startup_cannot_see_enterprise = await startup_repo.get_by_id(enterprise_record.id)
            enterprise_cannot_see_startup = await enterprise_repo.get_by_id(startup_record.id)

            assert startup_cannot_see_enterprise is None
            assert enterprise_cannot_see_startup is None

    async def test_malicious_actor_isolation(self, test_session_factory, comprehensive_contexts):
        """Test that malicious actors cannot access any legitimate workspace data."""
        async with test_session_factory() as session:
            # Create repositories for legitimate workspaces
            hr_repo = ComprehensiveTestRepository(
                session, comprehensive_contexts["enterprise_a_hr"]
            )
            finance_repo = ComprehensiveTestRepository(
                session, comprehensive_contexts["enterprise_a_finance"]
            )
            gov_repo = ComprehensiveTestRepository(
                session, comprehensive_contexts["gov_agency_classified"]
            )
            startup_repo = ComprehensiveTestRepository(
                session, comprehensive_contexts["startup_c_main"]
            )

            # Create repositories for malicious actors
            attacker_repo = ComprehensiveTestRepository(
                session, comprehensive_contexts["external_attacker"]
            )
            insider_repo = ComprehensiveTestRepository(
                session, comprehensive_contexts["insider_threat"]
            )

            # Create sensitive data in legitimate workspaces
            hr_secret = await hr_repo.create(name="HR Secret", category="confidential")
            finance_secret = await finance_repo.create(
                name="Finance Secret", category="confidential"
            )
            gov_secret = await gov_repo.create(name="Gov Secret", category="classified")
            startup_secret = await startup_repo.create(name="Startup Secret", category="innovation")

            # Test that external attacker cannot access any data
            attacker_cannot_see_hr = await attacker_repo.get_by_id(hr_secret.id)
            attacker_cannot_see_finance = await attacker_repo.get_by_id(finance_secret.id)
            attacker_cannot_see_gov = await attacker_repo.get_by_id(gov_secret.id)
            attacker_cannot_see_startup = await attacker_repo.get_by_id(startup_secret.id)

            assert attacker_cannot_see_hr is None
            assert attacker_cannot_see_finance is None
            assert attacker_cannot_see_gov is None
            assert attacker_cannot_see_startup is None

            # Test that insider threat cannot access any data
            insider_cannot_see_hr = await insider_repo.get_by_id(hr_secret.id)
            insider_cannot_see_finance = await insider_repo.get_by_id(finance_secret.id)
            insider_cannot_see_gov = await insider_repo.get_by_id(gov_secret.id)
            insider_cannot_see_startup = await insider_repo.get_by_id(startup_secret.id)

            assert insider_cannot_see_hr is None
            assert insider_cannot_see_finance is None
            assert insider_cannot_see_gov is None
            assert insider_cannot_see_startup is None

            # Test that malicious actors see empty workspaces
            attacker_list = await attacker_repo.list_all()
            insider_list = await insider_repo.list_all()

            assert len(attacker_list) == 0
            assert len(insider_list) == 0

    async def test_repository_factory_comprehensive_isolation(
        self, test_session_factory, comprehensive_contexts
    ):
        """Test comprehensive isolation through repository factory pattern."""
        async with test_session_factory() as session:
            # Create repository factories for different contexts
            factories = {}
            repos = {}

            for context_name, context in comprehensive_contexts.items():
                factories[context_name] = RepositoryFactory(session, context)
                repos[context_name] = factories[context_name].create_repository(
                    ComprehensiveTestRepository
                )

            # Create unique data in each workspace
            created_records = {}
            for context_name, repo in repos.items():
                record = await repo.create(
                    name=f"Record for {context_name}",
                    description=f"Data specific to {context_name}",
                    category=context_name.split("_")[0],  # enterprise, startup, gov, etc.
                )
                created_records[context_name] = record

            # Test that each repository only sees its own data
            for context_name, repo in repos.items():
                records = await repo.list_all()
                assert len(records) == 1
                assert records[0].name == f"Record for {context_name}"
                assert records[0].workspace_id == comprehensive_contexts[context_name].workspace_id

            # Test cross-workspace access prevention for all combinations
            for context1_name, repo1 in repos.items():
                for context2_name, record2 in created_records.items():
                    if context1_name != context2_name:
                        # Repo1 should not be able to see record2
                        cannot_see = await repo1.get_by_id(record2.id)
                        assert cannot_see is None, (
                            f"{context1_name} should not see {context2_name} data"
                        )

    async def test_workspace_isolation_under_load(
        self, test_session_factory, comprehensive_contexts
    ):
        """Test workspace isolation under high load with concurrent operations."""
        async with test_session_factory() as session:
            import asyncio

            # Create repositories for different workspaces
            hr_repo = ComprehensiveTestRepository(
                session, comprehensive_contexts["enterprise_a_hr"]
            )
            finance_repo = ComprehensiveTestRepository(
                session, comprehensive_contexts["enterprise_a_finance"]
            )
            startup_repo = ComprehensiveTestRepository(
                session, comprehensive_contexts["startup_c_main"]
            )

            # Define concurrent operations
            async def create_hr_records():
                records = []
                for i in range(20):
                    record = await hr_repo.create(
                        name=f"HR Record {i:03d}", category="hr", priority=i % 3 + 1
                    )
                    records.append(record)
                return records

            async def create_finance_records():
                records = []
                for i in range(15):
                    record = await finance_repo.create(
                        name=f"Finance Record {i:03d}", category="finance", priority=i % 3 + 1
                    )
                    records.append(record)
                return records

            async def create_startup_records():
                records = []
                for i in range(10):
                    record = await startup_repo.create(
                        name=f"Startup Record {i:03d}", category="startup", priority=i % 3 + 1
                    )
                    records.append(record)
                return records

            # Run concurrent operations
            hr_records, finance_records, startup_records = await asyncio.gather(
                create_hr_records(), create_finance_records(), create_startup_records()
            )

            # Verify isolation after concurrent operations
            hr_list = await hr_repo.list_all()
            finance_list = await finance_repo.list_all()
            startup_list = await startup_repo.list_all()

            assert len(hr_list) == 20
            assert len(finance_list) == 15
            assert len(startup_list) == 10

            # Verify all records belong to correct workspaces
            assert all(r.workspace_id == "enterprise-a-hr" for r in hr_list)
            assert all(r.workspace_id == "enterprise-a-finance" for r in finance_list)
            assert all(r.workspace_id == "startup-c-main" for r in startup_list)

            # Test cross-workspace access prevention after load
            for finance_record in finance_records[:5]:  # Test sample
                hr_cannot_see = await hr_repo.get_by_id(finance_record.id)
                startup_cannot_see = await startup_repo.get_by_id(finance_record.id)
                assert hr_cannot_see is None
                assert startup_cannot_see is None

    async def test_workspace_isolation_with_complex_queries(
        self, test_session_factory, comprehensive_contexts
    ):
        """Test workspace isolation with complex filtering and search operations."""
        async with test_session_factory() as session:
            hr_repo = ComprehensiveTestRepository(
                session, comprehensive_contexts["enterprise_a_hr"]
            )
            finance_repo = ComprehensiveTestRepository(
                session, comprehensive_contexts["enterprise_a_finance"]
            )

            # Create overlapping data patterns in different workspaces
            categories = ["urgent", "normal", "low"]
            priorities = [1, 2, 3]

            for i in range(30):
                await hr_repo.create(
                    name=f"HR Task {i:03d}",
                    category=categories[i % 3],
                    priority=priorities[i % 3],
                    is_active=(i % 2 == 0),
                )

                await finance_repo.create(
                    name=f"Finance Task {i:03d}",
                    category=categories[i % 3],
                    priority=priorities[i % 3],
                    is_active=(i % 2 == 0),
                )

            # Test complex filtering maintains workspace isolation
            hr_urgent_active = await hr_repo.find_active_by_category("urgent")
            finance_urgent_active = await finance_repo.find_active_by_category("urgent")

            # Should find same pattern but different workspaces
            assert len(hr_urgent_active) == len(finance_urgent_active)
            assert all(r.workspace_id == "enterprise-a-hr" for r in hr_urgent_active)
            assert all(r.workspace_id == "enterprise-a-finance" for r in finance_urgent_active)

            # Test count operations with complex filters
            hr_high_priority = await hr_repo.get_high_priority_count()
            finance_high_priority = await finance_repo.get_high_priority_count()

            assert hr_high_priority == finance_high_priority  # Same pattern
            assert hr_high_priority == 10  # Every 3rd record with priority 3

            # Test pagination maintains isolation
            hr_page1 = await hr_repo.list_all(limit=10, offset=0)
            hr_page2 = await hr_repo.list_all(limit=10, offset=10)
            finance_page1 = await finance_repo.list_all(limit=10, offset=0)

            assert len(hr_page1) == 10
            assert len(hr_page2) == 10
            assert len(finance_page1) == 10

            assert all(r.workspace_id == "enterprise-a-hr" for r in hr_page1 + hr_page2)
            assert all(r.workspace_id == "enterprise-a-finance" for r in finance_page1)

    async def test_workspace_isolation_data_integrity(
        self, test_session_factory, comprehensive_contexts
    ):
        """Test that workspace isolation maintains data integrity across operations."""
        async with test_session_factory() as session:
            hr_repo = ComprehensiveTestRepository(
                session, comprehensive_contexts["enterprise_a_hr"]
            )
            finance_repo = ComprehensiveTestRepository(
                session, comprehensive_contexts["enterprise_a_finance"]
            )

            # Create initial data
            hr_record = await hr_repo.create(name="HR Original", priority=1)
            finance_record = await finance_repo.create(name="Finance Original", priority=1)

            # Test that updates don't affect other workspaces
            updated_hr = await hr_repo.update(hr_record.id, name="HR Updated", priority=3)
            updated_finance = await finance_repo.update(
                finance_record.id, name="Finance Updated", priority=2
            )

            assert updated_hr.name == "HR Updated"
            assert updated_hr.priority == 3
            assert updated_finance.name == "Finance Updated"
            assert updated_finance.priority == 2

            # Verify isolation is maintained
            hr_list = await hr_repo.list_all()
            finance_list = await finance_repo.list_all()

            assert len(hr_list) == 1
            assert len(finance_list) == 1
            assert hr_list[0].name == "HR Updated"
            assert finance_list[0].name == "Finance Updated"

            # Test deletion isolation
            deleted_hr = await hr_repo.delete(hr_record.id)
            assert deleted_hr is True

            # Verify finance record is unaffected
            finance_still_exists = await finance_repo.get_by_id(finance_record.id)
            assert finance_still_exists is not None
            assert finance_still_exists.name == "Finance Updated"

            # Verify HR workspace is now empty
            hr_empty = await hr_repo.list_all()
            assert len(hr_empty) == 0

            # Verify finance workspace still has data
            finance_still_has_data = await finance_repo.list_all()
            assert len(finance_still_has_data) == 1
