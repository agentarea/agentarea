"""``reasoning_effort`` is one of the known levels, or nothing."""

import pytest
from agentarea_common.reasoning_effort import reasoning_effort_of


@pytest.mark.parametrize(
    "parameters", [None, {}, {"reasoning_effort": None}, {"reasoning_effort": ""}]
)
def test_no_effort_is_none(parameters):
    assert reasoning_effort_of(parameters) is None


@pytest.mark.parametrize("value", ["minimal", "low", "medium", "high"])
def test_a_known_level_is_returned(value):
    assert reasoning_effort_of({"reasoning_effort": value}) == value


@pytest.mark.parametrize("value", ["max", "HIGH", 3, ["low"]])
def test_anything_else_is_refused(value):
    with pytest.raises(ValueError, match="reasoning_effort must be one of"):
        reasoning_effort_of({"reasoning_effort": value})
