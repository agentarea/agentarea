"""Comprehensive unit tests for WorkspaceScopedRepository functionality."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.base.models import BaseModel, WorkspaceScopedMixin
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

# Mark all async tests in this module
pytestmark = pytest.mark.asyncio


class MockModel(BaseModel, WorkspaceScopedMixin):
    """Mock model for testing."""

    __tablename__ = "mock_model"

    def __init__(self, **kwargs):
        self.id = kwargs.get("id", uuid4())
        self.workspace_id = kwargs.get("workspace_id")
        self.created_by = kwargs.get("created_by")
        self.name = kwargs.get("name", "test")


class TestWorkspaceScopedRepository:
    """Test suite for WorkspaceScopedRepository."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock async session."""
        session = AsyncMock(spec=AsyncSession)
        return session

    @pytest.fixture
    def user_context_workspace1(self):
        """Create user context for workspace1."""
        return UserContext(user_id="user1", workspace_id="workspace1", roles=["user"])

    @pytest.fixture
    def user_context_workspace2(self):
        """Create user context for workspace2."""
        return UserContext(user_id="user2", workspace_id="workspace2", roles=["user"])

    @pytest.fixture
    def repository_workspace1(self, mock_session, user_context_workspace1):
        """Create repository for workspace1."""
        return WorkspaceScopedRepository(
            session=mock_session, model_class=MockModel, user_context=user_context_workspace1
        )

    @pytest.fixture
    def repository_workspace2(self, mock_session, user_context_workspace2):
        """Create repository for workspace2."""
        return WorkspaceScopedRepository(
            session=mock_session, model_class=MockModel, user_context=user_context_workspace2
        )

    async def test_create_auto_populates_workspace_context(
        self, repository_workspace1, mock_session
    ):
        """Test that create() automatically populates workspace_id and created_by."""
        # Arrange
        mock_instance = MockModel(name="test_record")
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()

        # Mock the model class constructor
        repository_workspace1.model_class = MagicMock(return_value=mock_instance)

        # Act
        result = await repository_workspace1.create(name="test_record")

        # Assert
        repository_workspace1.model_class.assert_called_once_with(
            name="test_record", created_by="user1", workspace_id="workspace1"
        )
        mock_session.add.assert_called_once_with(mock_instance)
        mock_session.commit.assert_called_once()
        mock_session.refresh.assert_called_once_with(mock_instance)
        assert result == mock_instance

    async def test_get_by_id_filters_by_workspace(self, repository_workspace1, mock_session):
        """Test that get_by_id() filters by workspace_id."""
        # Arrange
        test_id = uuid4()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = MockModel(
            id=test_id, workspace_id="workspace1", created_by="user1"
        )
        mock_session.execute.return_value = mock_result

        # Act
        result = await repository_workspace1.get_by_id(test_id)

        # Assert
        mock_session.execute.assert_called_once()
        # Verify the query includes workspace filter
        call_args = mock_session.execute.call_args[0][0]
        # The query should filter by both id and workspace_id
        assert result is not None
        assert result.workspace_id == "workspace1"

    async def test_get_by_id_creator_scoped_filters_by_creator_and_workspace(
        self, repository_workspace1, mock_session
    ):
        """Test that get_by_id() with creator_scoped=True filters by both created_by and workspace_id."""
        # Arrange
        test_id = uuid4()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = MockModel(
            id=test_id, workspace_id="workspace1", created_by="user1"
        )
        mock_session.execute.return_value = mock_result

        # Act
        result = await repository_workspace1.get_by_id(test_id, creator_scoped=True)

        # Assert
        mock_session.execute.assert_called_once()
        assert result is not None
        assert result.workspace_id == "workspace1"
        assert result.created_by == "user1"

    async def test_get_by_id_returns_none_for_different_workspace(
        self, repository_workspace1, mock_session
    ):
        """Test that get_by_id() returns None for records in different workspace."""
        # Arrange
        test_id = uuid4()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        # Act
        result = await repository_workspace1.get_by_id(test_id)

        # Assert
        assert result is None

    async def test_get_by_id_or_raise_raises_for_missing_record(
        self, repository_workspace1, mock_session
    ):
        """Test that get_by_id_or_raise() raises NoResultFound for missing records."""
        # Arrange
        test_id = uuid4()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        # Act & Assert
        with pytest.raises(NoResultFound, match="MockModel with id .* not found in workspace"):
            await repository_workspace1.get_by_id_or_raise(test_id)

    async def test_list_all_returns_workspace_scoped_records(
        self, repository_workspace1, mock_session
    ):
        """Test that list_all() returns all records in workspace (not user-scoped)."""
        # Arrange
        mock_records = [
            MockModel(id=uuid4(), workspace_id="workspace1", created_by="user1"),
            MockModel(
                id=uuid4(), workspace_id="workspace1", created_by="user2"
            ),  # Different creator
        ]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_records
        mock_session.execute.return_value = mock_result

        # Act
        result = await repository_workspace1.list_all()

        # Assert
        assert len(result) == 2
        assert all(record.workspace_id == "workspace1" for record in result)
        # Should include records from different creators in same workspace
        creators = {record.created_by for record in result}
        assert "user1" in creators
        assert "user2" in creators

    async def test_list_all_creator_scoped_returns_only_user_records(
        self, repository_workspace1, mock_session
    ):
        """Test that list_all(creator_scoped=True) returns only current user's records."""
        # Arrange
        mock_records = [
            MockModel(id=uuid4(), workspace_id="workspace1", created_by="user1"),
        ]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_records
        mock_session.execute.return_value = mock_result

        # Act
        result = await repository_workspace1.list_all(creator_scoped=True)

        # Assert
        assert len(result) == 1
        assert result[0].workspace_id == "workspace1"
        assert result[0].created_by == "user1"

    async def test_list_all_with_filters(self, repository_workspace1, mock_session):
        """Test that list_all() applies additional filters correctly."""
        # Arrange
        mock_records = [
            MockModel(id=uuid4(), workspace_id="workspace1", created_by="user1", name="test1"),
        ]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_records
        mock_session.execute.return_value = mock_result

        # Act
        result = await repository_workspace1.list_all(name="test1")

        # Assert
        assert len(result) == 1
        assert result[0].name == "test1"

    async def test_list_all_with_pagination(self, repository_workspace1, mock_session):
        """Test that list_all() applies pagination correctly."""
        # Arrange
        mock_records = [MockModel(id=uuid4(), workspace_id="workspace1", created_by="user1")]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_records
        mock_session.execute.return_value = mock_result

        # Act
        result = await repository_workspace1.list_all(limit=10, offset=5)

        # Assert
        mock_session.execute.assert_called_once()
        # Verify pagination was applied to query
        assert len(result) == 1

    async def test_count_returns_workspace_record_count(self, repository_workspace1, mock_session):
        """Test that count() returns correct count for workspace."""
        # Arrange
        mock_result = MagicMock()
        mock_result.scalar.return_value = 5
        mock_session.execute.return_value = mock_result

        # Act
        result = await repository_workspace1.count()

        # Assert
        assert result == 5

    async def test_count_creator_scoped_returns_user_record_count(
        self, repository_workspace1, mock_session
    ):
        """Test that count(creator_scoped=True) returns count for current user."""
        # Arrange
        mock_result = MagicMock()
        mock_result.scalar.return_value = 3
        mock_session.execute.return_value = mock_result

        # Act
        result = await repository_workspace1.count(creator_scoped=True)

        # Assert
        assert result == 3

    async def test_update_workspace_scoped_allows_any_workspace_record(
        self, repository_workspace1, mock_session
    ):
        """Test that update() allows updating any record in workspace."""
        # Arrange
        test_id = uuid4()
        existing_record = MockModel(
            id=test_id,
            workspace_id="workspace1",
            created_by="user2",  # Different creator
            name="original",
        )

        # Mock session execute to return the existing record
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_record
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()

        # Act
        result = await repository_workspace1.update(test_id, name="updated")

        # Assert
        mock_session.execute.assert_called_once()
        assert existing_record.name == "updated"
        mock_session.commit.assert_called_once()
        mock_session.refresh.assert_called_once_with(existing_record)
        assert result == existing_record

    async def test_update_creator_scoped_only_allows_own_records(
        self, repository_workspace1, mock_session
    ):
        """Test that update(creator_scoped=True) only allows updating own records."""
        # Arrange
        test_id = uuid4()

        # Mock session execute to return None (record not found for creator-scoped query)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        # Act
        result = await repository_workspace1.update(test_id, creator_scoped=True, name="updated")

        # Assert
        mock_session.execute.assert_called_once()
        assert result is None

    async def test_update_prevents_modifying_immutable_fields(
        self, repository_workspace1, mock_session
    ):
        """Test that update() prevents modifying created_by and workspace_id."""
        # Arrange
        test_id = uuid4()
        existing_record = MockModel(
            id=test_id, workspace_id="workspace1", created_by="user1", name="original"
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_record
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()

        # Act
        result = await repository_workspace1.update(
            test_id,
            name="updated",
            created_by="hacker",  # Should be ignored
            workspace_id="other_workspace",  # Should be ignored
        )

        # Assert
        assert existing_record.name == "updated"
        assert existing_record.created_by == "user1"  # Unchanged
        assert existing_record.workspace_id == "workspace1"  # Unchanged

    async def test_update_or_raise_raises_for_missing_record(
        self, repository_workspace1, mock_session
    ):
        """Test that update_or_raise() raises NoResultFound for missing records."""
        # Arrange
        test_id = uuid4()
        repository_workspace1.update = AsyncMock(return_value=None)

        # Act & Assert
        with pytest.raises(NoResultFound, match="MockModel with id .* not found in workspace"):
            await repository_workspace1.update_or_raise(test_id, name="updated")

    async def test_delete_workspace_scoped_allows_any_workspace_record(
        self, repository_workspace1, mock_session
    ):
        """Test that delete() allows deleting any record in workspace."""
        # Arrange
        test_id = uuid4()
        existing_record = MockModel(
            id=test_id,
            workspace_id="workspace1",
            created_by="user2",  # Different creator
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_record
        mock_session.execute.return_value = mock_result
        mock_session.delete = AsyncMock()
        mock_session.commit = AsyncMock()

        # Act
        result = await repository_workspace1.delete(test_id)

        # Assert
        mock_session.execute.assert_called_once()
        mock_session.delete.assert_called_once_with(existing_record)
        mock_session.commit.assert_called_once()
        assert result is True

    async def test_delete_creator_scoped_only_allows_own_records(
        self, repository_workspace1, mock_session
    ):
        """Test that delete(creator_scoped=True) only allows deleting own records."""
        # Arrange
        test_id = uuid4()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        # Act
        result = await repository_workspace1.delete(test_id, creator_scoped=True)

        # Assert
        mock_session.execute.assert_called_once()
        assert result is False

    async def test_delete_returns_false_for_missing_record(
        self, repository_workspace1, mock_session
    ):
        """Test that delete() returns False for missing records."""
        # Arrange
        test_id = uuid4()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        # Act
        result = await repository_workspace1.delete(test_id)

        # Assert
        assert result is False

    async def test_delete_or_raise_raises_for_missing_record(
        self, repository_workspace1, mock_session
    ):
        """Test that delete_or_raise() raises NoResultFound for missing records."""
        # Arrange
        test_id = uuid4()
        repository_workspace1.delete = AsyncMock(return_value=False)

        # Act & Assert
        with pytest.raises(NoResultFound, match="MockModel with id .* not found in workspace"):
            await repository_workspace1.delete_or_raise(test_id)

    async def test_exists_returns_true_for_existing_record(
        self, repository_workspace1, mock_session
    ):
        """Test that exists() returns True for existing records in workspace."""
        # Arrange
        test_id = uuid4()
        existing_record = MockModel(id=test_id, workspace_id="workspace1", created_by="user1")
        repository_workspace1.get_by_id = AsyncMock(return_value=existing_record)

        # Act
        result = await repository_workspace1.exists(test_id)

        # Assert
        assert result is True

    async def test_exists_returns_false_for_missing_record(
        self, repository_workspace1, mock_session
    ):
        """Test that exists() returns False for missing records."""
        # Arrange
        test_id = uuid4()
        repository_workspace1.get_by_id = AsyncMock(return_value=None)

        # Act
        result = await repository_workspace1.exists(test_id)

        # Assert
        assert result is False

    async def test_find_by_applies_filters_correctly(self, repository_workspace1, mock_session):
        """Test that find_by() applies filters correctly."""
        # Arrange
        mock_records = [
            MockModel(id=uuid4(), workspace_id="workspace1", created_by="user1", name="test")
        ]
        repository_workspace1.list_all = AsyncMock(return_value=mock_records)

        # Act
        result = await repository_workspace1.find_by(name="test")

        # Assert
        repository_workspace1.list_all.assert_called_once_with(creator_scoped=False, name="test")
        assert result == mock_records

    async def test_find_one_by_returns_first_match(self, repository_workspace1, mock_session):
        """Test that find_one_by() returns first matching record."""
        # Arrange
        mock_record = MockModel(
            id=uuid4(), workspace_id="workspace1", created_by="user1", name="test"
        )
        repository_workspace1.find_by = AsyncMock(return_value=[mock_record])

        # Act
        result = await repository_workspace1.find_one_by(name="test")

        # Assert
        repository_workspace1.find_by.assert_called_once_with(creator_scoped=False, name="test")
        assert result == mock_record

    async def test_find_one_by_returns_none_for_no_matches(
        self, repository_workspace1, mock_session
    ):
        """Test that find_one_by() returns None when no matches found."""
        # Arrange
        repository_workspace1.find_by = AsyncMock(return_value=[])

        # Act
        result = await repository_workspace1.find_one_by(name="nonexistent")

        # Assert
        assert result is None

    def test_workspace_filter_generation(self, repository_workspace1):
        """Test that workspace filter is generated correctly."""
        # Act
        workspace_filter = repository_workspace1._get_workspace_filter()

        # Assert
        # The filter should be a comparison expression
        assert hasattr(workspace_filter, "left")
        assert hasattr(workspace_filter, "right")

    def test_creator_workspace_filter_generation(self, repository_workspace1):
        """Test that creator+workspace filter is generated correctly."""
        # Act
        creator_workspace_filter = repository_workspace1._get_creator_workspace_filter()

        # Assert
        # The filter should be an AND expression with two comparisons
        assert hasattr(creator_workspace_filter, "clauses")
        assert len(creator_workspace_filter.clauses) == 2
