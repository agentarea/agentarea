import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.permission import PermissionService
from agentarea_common.di.container import get_container

# Real (SQLite-backed) Temporal server fixtures, shared across packages. Needed
# for schedule tests: the time-skipping test server does not implement the
# Schedules API. See agentarea_common.testing.temporal for details. This module
# imports temporalio lazily (inside the fixture), so it is safe to import here
# even before the shim below.
from agentarea_common.testing.temporal import (  # noqa: F401
    temporal_sqlite_client,
    temporal_sqlite_env,
)


def pytest_configure(config):
    """Register markers used by this package's tests."""
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests (requiring real services)"
    )


# Only install the temporalio MagicMock shim when the real package is NOT
# importable. When temporalio is actually installed we must use the real
# modules so that ``except SomeTemporalError`` clauses catch genuine exception
# classes (a MagicMock is not a BaseException subclass and raises TypeError).
try:
    import temporalio  # noqa: F401

    _TEMPORALIO_AVAILABLE = True
except ImportError:
    _TEMPORALIO_AVAILABLE = False

if not _TEMPORALIO_AVAILABLE:
    temporalio_mock = MagicMock()
    sys.modules["temporalio"] = temporalio_mock
    sys.modules["temporalio.client"] = MagicMock()
    sys.modules["temporalio.worker"] = MagicMock()
    sys.modules["temporalio.activity"] = MagicMock()
    sys.modules["temporalio.workflow"] = MagicMock()
    sys.modules["temporalio.api"] = MagicMock()
    sys.modules["temporalio.api.common"] = MagicMock()
    sys.modules["temporalio.api.common.v1"] = MagicMock()
    sys.modules["temporalio.common"] = MagicMock()
    sys.modules["temporalio.exceptions"] = MagicMock()
    sys.modules["temporalio.service"] = MagicMock()


CALLER = UserContext(user_id="test-user", workspace_id="test-workspace")


class RecordingPermissions(PermissionService):
    """The PDP the trigger service asks before binding or starting an agent.

    Allows unless ``allowed`` is turned off, and remembers every question.
    """

    def __init__(self) -> None:
        self.allowed = True
        self.checks: list[tuple[str, str, str, str]] = []

    async def check(self, subject, permission, resource_type, resource_id) -> bool:
        self.checks.append((subject, permission, resource_type, resource_id))
        return self.allowed


@pytest.fixture(autouse=True)
def permissions():
    """Every test runs with a PDP registered; one that refuses turns ``allowed`` off."""
    container = get_container()
    saved = dict(container._singletons)
    recorder = RecordingPermissions()
    container.register_singleton(PermissionService, recorder)
    yield recorder
    container._singletons.clear()
    container._singletons.update(saved)


def active_agent_repository() -> AsyncMock:
    """An agent repository whose agent exists and is active, so a firing may run it."""
    repository = AsyncMock()
    repository.get.return_value = SimpleNamespace(status="active")
    return repository


def make_trigger_repository_factory(trigger_repo=None, execution_repo=None, agent_repo=None):
    """Build a mock RepositoryFactory for TriggerService.

    The new ``TriggerService.__init__`` signature takes a ``repository_factory``
    and lazily creates its repositories via ``factory.create_repository(cls)``.
    This helper returns a factory whose ``create_repository`` returns the SAME
    mock objects the tests assert on, keyed by repository class.
    """
    from agentarea_triggers.infrastructure.repository import (
        TriggerExecutionRepository,
        TriggerRepository,
    )

    trigger_repo = trigger_repo if trigger_repo is not None else AsyncMock()
    execution_repo = execution_repo if execution_repo is not None else AsyncMock()

    from agentarea_tasks.infrastructure.repository import TaskRepository

    # No run of the trigger is still going unless a test says so.
    task_repo = AsyncMock()
    task_repo.oldest_unfinished_from.return_value = None

    mapping = {
        TriggerRepository: trigger_repo,
        TriggerExecutionRepository: execution_repo,
        TaskRepository: task_repo,
    }

    try:
        from agentarea_agents.infrastructure.repository import AgentRepository

        mapping[AgentRepository] = (
            agent_repo if agent_repo is not None else active_agent_repository()
        )
    except ImportError:
        pass

    factory = MagicMock()
    factory.create_repository.side_effect = lambda cls, *a, **k: mapping.get(cls, AsyncMock())
    factory.session = AsyncMock()
    factory.user_context = CALLER
    return factory


@pytest.fixture
def trigger_repository_factory():
    """Fixture exposing the repository-factory builder helper."""
    return make_trigger_repository_factory


@pytest.fixture(autouse=True)
def _reset_correlation_id():
    """Reset the correlation-id contextvar after each test.

    Several code paths call ``set_correlation_id`` (or implicitly set it via
    ``TriggerLogger``); without resetting, the value leaks into later tests and
    breaks assertions that expect a clean ``None`` starting state.
    """
    yield
    try:
        from agentarea_triggers.logging_utils import correlation_id_context

        correlation_id_context.set(None)
    except ImportError:
        pass
