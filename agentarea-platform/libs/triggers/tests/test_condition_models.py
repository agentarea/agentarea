"""Every LLM condition names its own model, which exists here and can answer it."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from agentarea_triggers.condition_models import validate_condition_models
from agentarea_triggers.logging_utils import TriggerValidationError


class _Instances:
    def __init__(self, **kinds: str):
        self._by_id = {
            instance_id: SimpleNamespace(model_spec=SimpleNamespace(kind=kind))
            for instance_id, kind in kinds.items()
        }

    async def get_by_id(self, instance_id):
        return self._by_id.get(str(instance_id))


CHAT, DECISION, IMAGE = str(uuid4()), str(uuid4()), str(uuid4())
INSTANCES = _Instances(**{CHAT: "chat", DECISION: "decision", IMAGE: "image"})


def _llm(model_id: str | None = None) -> dict:
    condition = {"type": "llm", "description": "a refund request"}
    if model_id is not None:
        condition["model_id"] = model_id
    return condition


@pytest.mark.parametrize("model_id", [CHAT, DECISION])
async def test_a_chat_or_decision_model_is_accepted(model_id):
    await validate_condition_models(_llm(model_id), INSTANCES)


async def test_conditions_without_llm_parts_need_no_model():
    await validate_condition_models(None, INSTANCES)
    await validate_condition_models({"field_matches": {"a": 1}}, INSTANCES)
    await validate_condition_models({"type": "rule", "rules": []}, INSTANCES)


@pytest.mark.parametrize(
    "conditions, message",
    [
        (_llm(), "needs a model_id"),
        (_llm("not-a-uuid"), "not a model instance id"),
        (_llm(str(uuid4())), "does not exist in this workspace"),
        (_llm(IMAGE), "image model"),
        ({"description": "no type is an llm condition"}, "needs a model_id"),
    ],
)
async def test_a_bad_model_is_refused(conditions, message):
    with pytest.raises(TriggerValidationError, match=message):
        await validate_condition_models(conditions, INSTANCES)


async def test_each_sub_condition_of_a_combined_condition_is_checked():
    combined = {
        "type": "combined",
        "logic": "AND",
        "conditions": [_llm(CHAT), {"type": "combined", "conditions": [_llm()]}],
    }

    with pytest.raises(TriggerValidationError, match="needs a model_id"):
        await validate_condition_models(combined, INSTANCES)


def _service(instances):
    from unittest.mock import AsyncMock, MagicMock

    from agentarea_llm.infrastructure.model_instance_repository import ModelInstanceRepository
    from agentarea_triggers.trigger_service import TriggerService

    from .conftest import make_trigger_repository_factory

    factory = make_trigger_repository_factory()
    others = factory.create_repository.side_effect
    factory.create_repository.side_effect = lambda cls, *a, **k: (
        instances if cls is ModelInstanceRepository else others(cls, *a, **k)
    )
    return TriggerService(
        repository_factory=factory, event_broker=AsyncMock(), task_service=MagicMock()
    )


def _cron(conditions: dict):
    from agentarea_triggers.domain.enums import TriggerType
    from agentarea_triggers.domain.models import TriggerCreate

    return TriggerCreate(
        name="Refunds",
        agent_id=uuid4(),
        trigger_type=TriggerType.CRON,
        cron_expression="0 9 * * *",
        task_parameters={"text": "check refunds"},
        conditions=conditions,
        created_by="u-1",
    )


async def test_trigger_creation_refuses_a_condition_without_its_model():
    with pytest.raises(TriggerValidationError, match="needs a model_id"):
        await _service(INSTANCES).validate_configuration(_cron(_llm()))


async def test_trigger_creation_accepts_a_decision_model():
    await _service(INSTANCES).validate_configuration(_cron(_llm(DECISION)))


async def test_a_trigger_update_is_checked_too():
    from unittest.mock import AsyncMock

    from agentarea_triggers.domain.models import TriggerUpdate

    service = _service(INSTANCES)
    service.get_trigger = AsyncMock(return_value=SimpleNamespace(id=uuid4()))

    with pytest.raises(TriggerValidationError, match="image model"):
        await service.update_trigger(uuid4(), TriggerUpdate(conditions=_llm(IMAGE)))
