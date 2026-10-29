"""``model_override`` names a model instance by id, or nothing."""

import pytest
from agentarea_common.model_override import model_override_of

MODEL = "aad7c8d9-756e-58e0-b42f-80ba341616df"


@pytest.mark.parametrize("parameters", [None, {}, {"model_override": None}, {"model_override": ""}])
def test_no_override_is_none(parameters):
    assert model_override_of(parameters) is None


def test_an_instance_id_is_returned_normalized():
    assert model_override_of({"model_override": MODEL.upper()}) == MODEL


@pytest.mark.parametrize("value", ["gpt-4o", 42, ["x"], "not-a-uuid"])
def test_anything_else_is_refused(value):
    with pytest.raises(ValueError, match="model instance id"):
        model_override_of({"model_override": value})
