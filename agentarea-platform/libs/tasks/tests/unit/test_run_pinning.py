from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_agents.serving.pinning import RunPin
from agentarea_tasks.task_service import TaskService


def _service(pinner) -> TaskService:
    service = TaskService.__new__(TaskService)
    service.agent_repository = MagicMock()
    service._run_pinner = lambda: pinner
    return service


def _pinner(*, owned_revision=True):
    current = SimpleNamespace(id=uuid4())
    explicit = SimpleNamespace(id=uuid4())
    revisions = SimpleNamespace(
        ensure_current=AsyncMock(return_value=current),
        get=AsyncMock(return_value=explicit if owned_revision else None),
    )
    return SimpleNamespace(
        revisions=revisions,
        pin=AsyncMock(return_value=RunPin(revision_id=uuid4(), experiment_id=uuid4(), arm="candidate")),
        current=current,
        explicit=explicit,
    )


async def test_a_plain_run_is_assigned_by_the_pinner():
    pinner = _pinner()

    pin = await _service(pinner)._pin_run(SimpleNamespace(id=uuid4()), uuid4(), {}, None)

    assert pin is pinner.pin.return_value


async def test_a_run_with_its_own_resources_is_not_an_experiment_sample():
    pinner = _pinner()

    pin = await _service(pinner)._pin_run(
        SimpleNamespace(id=uuid4()), uuid4(), {"model_override": "m-2"}, None
    )

    assert pin == RunPin(revision_id=pinner.current.id)
    pinner.pin.assert_not_awaited()


async def test_an_explicit_revision_is_used_as_given():
    pinner = _pinner()

    pin = await _service(pinner)._pin_run(
        SimpleNamespace(id=uuid4()), uuid4(), {}, pinner.explicit.id
    )

    assert pin == RunPin(revision_id=pinner.explicit.id)


async def test_an_explicit_revision_of_another_agent_is_refused():
    pinner = _pinner(owned_revision=False)

    with pytest.raises(ValueError, match="does not belong"):
        await _service(pinner)._pin_run(SimpleNamespace(id=uuid4()), uuid4(), {}, uuid4())


async def test_an_explicit_revision_refuses_per_run_overrides():
    pinner = _pinner()

    with pytest.raises(ValueError, match="overrides"):
        await _service(pinner)._pin_run(
            SimpleNamespace(id=uuid4()), uuid4(), {"skills": ["s"]}, pinner.explicit.id
        )


async def test_without_an_agent_repository_nothing_is_pinned():
    service = TaskService.__new__(TaskService)
    service.agent_repository = None

    assert await service._pin_run(None, uuid4(), {}, None) is None
