"""Test backward compatibility of enhanced SimpleTask model."""

from uuid import uuid4

from agentarea_tasks.domain.models import SimpleTask


class TestSimpleTaskBackwardCompatibility:
    """Test that enhanced SimpleTask maintains backward compatibility."""

    def test_original_usage_pattern_still_works(self):
        """Test that the original SimpleTask usage pattern still works."""
        # This mimics how SimpleTask was used in the original test file
        agent_id = uuid4()
        task_id = uuid4()

        task = SimpleTask(
            id=task_id,
            title="Test Task",
            description="This is a test task",
            query="What is 2+2?",
            user_id="user123",
            agent_id=agent_id,
            task_parameters={"param1": "value1"},
            status="submitted"
        )

        # Verify all original fields work as expected
        assert task.id == task_id
        assert task.title == "Test Task"
        assert task.description == "This is a test task"
        assert task.query == "What is 2+2?"
        assert task.user_id == "user123"
        assert task.agent_id == agent_id
        assert task.task_parameters == {"param1": "value1"}
        assert task.status == "submitted"
        assert task.result is None
        assert task.error_message is None

        # Verify new fields have sensible defaults
        assert task.metadata == {}
        assert task.started_at is None
        assert task.completed_at is None
        assert task.execution_id is None
        assert task.updated_at == task.created_at

    def test_mock_repository_pattern_compatibility(self):
        """Test that the mock repository pattern from existing tests still works."""
        # This mimics the MockTaskRepository usage pattern
        tasks = {}

        # Create task like in the original test
        task = SimpleTask(
            id=uuid4(),
            title="Repository Test",
            description="Test repository compatibility",
            query="Test query",
            user_id="user123",
            agent_id=uuid4(),
        )

        # Store in mock repository
        tasks[str(task.id)] = task

        # Retrieve from mock repository
        retrieved_task = tasks.get(str(task.id))

        assert retrieved_task is not None
        assert retrieved_task.id == task.id
        assert retrieved_task.title == "Repository Test"

        # Verify enhanced fields don't break the pattern
        assert hasattr(retrieved_task, 'metadata')
        assert hasattr(retrieved_task, 'started_at')
        assert hasattr(retrieved_task, 'completed_at')
        assert hasattr(retrieved_task, 'execution_id')

    def test_filtering_patterns_still_work(self):
        """Test that filtering patterns from existing tests still work."""
        # Create multiple tasks like in the original tests
        agent1_id = uuid4()
        agent2_id = uuid4()

        tasks = [
            SimpleTask(
                id=uuid4(),
                title="Task 1",
                description="Description 1",
                query="Query 1",
                user_id="user1",
                agent_id=agent1_id,
            ),
            SimpleTask(
                id=uuid4(),
                title="Task 2",
                description="Description 2",
                query="Query 2",
                user_id="user1",
                agent_id=agent1_id,
            ),
            SimpleTask(
                id=uuid4(),
                title="Task 3",
                description="Description 3",
                query="Query 3",
                user_id="user2",
                agent_id=agent2_id,
            ),
        ]

        # Test user filtering (from original test)
        user1_tasks = [task for task in tasks if task.user_id == "user1"]
        assert len(user1_tasks) == 2
        assert all(task.user_id == "user1" for task in user1_tasks)

        # Test agent filtering (from original test)
        agent1_tasks = [task for task in tasks if task.agent_id == agent1_id]
        assert len(agent1_tasks) == 2
        assert all(task.agent_id == agent1_id for task in agent1_tasks)

    def test_task_creation_with_defaults_unchanged(self):
        """Test that default values haven't changed from original behavior."""
        task = SimpleTask(
            id=uuid4(),
            title="Default Test",
            description="Test defaults",
            query="test query",
            user_id="test_user",
            agent_id=uuid4()
        )

        # These defaults should match the original SimpleTask behavior
        assert task.status == "submitted"  # Original default
        assert task.task_parameters == {}  # Original default
        assert task.result is None  # Original default
        assert task.error_message is None  # Original default

        # New fields should have sensible defaults that don't break existing code
        assert task.metadata == {}
        assert task.started_at is None
        assert task.completed_at is None
        assert task.execution_id is None

    def test_serialization_compatibility(self):
        """Test that serialization patterns still work."""
        task = SimpleTask(
            id=uuid4(),
            title="Serialization Test",
            description="Test serialization",
            query="serialize this",
            user_id="serialize_user",
            agent_id=uuid4(),
            task_parameters={"key": "value"}
        )

        # Test dict conversion (common pattern)
        task_dict = task.model_dump()

        # Verify original fields are present
        assert "id" in task_dict
        assert "title" in task_dict
        assert "description" in task_dict
        assert "query" in task_dict
        assert "user_id" in task_dict
        assert "agent_id" in task_dict
        assert "status" in task_dict
        assert "task_parameters" in task_dict
        assert "result" in task_dict
        assert "error_message" in task_dict
        assert "created_at" in task_dict

        # Verify new fields are also present
        assert "updated_at" in task_dict
        assert "started_at" in task_dict
        assert "completed_at" in task_dict
        assert "execution_id" in task_dict
        assert "metadata" in task_dict

        # Test reconstruction from dict
        reconstructed_task = SimpleTask(**task_dict)
        assert reconstructed_task.id == task.id
        assert reconstructed_task.title == task.title
        assert reconstructed_task.metadata == task.metadata
