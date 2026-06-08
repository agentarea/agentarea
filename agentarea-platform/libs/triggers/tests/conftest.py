import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

# Mock temporalio if not present
if "temporalio" not in sys.modules:
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
