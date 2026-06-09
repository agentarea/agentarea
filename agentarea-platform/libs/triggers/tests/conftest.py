import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

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


def make_trigger_repository_factory(
    trigger_repo=None, execution_repo=None, agent_repo=None
):
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

    mapping = {
        TriggerRepository: trigger_repo,
        TriggerExecutionRepository: execution_repo,
    }

    try:
        from agentarea_agents.infrastructure.repository import AgentRepository

        mapping[AgentRepository] = (
            agent_repo if agent_repo is not None else AsyncMock()
        )
    except ImportError:
        pass

    factory = MagicMock()
    factory.create_repository.side_effect = lambda cls, *a, **k: mapping.get(
        cls, AsyncMock()
    )
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
