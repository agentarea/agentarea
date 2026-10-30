"""Reasoning is a level or a token budget; which levels a model takes is catalog data."""

import pytest
from agentarea_common.reasoning_effort import (
    check_reasoning,
    reasoning_effort_of,
    reasoning_max_tokens_of,
    reasoning_settings,
)


@pytest.mark.parametrize(
    "parameters", [None, {}, {"reasoning_effort": None}, {"reasoning_effort": ""}]
)
def test_no_effort_is_none(parameters):
    assert reasoning_effort_of(parameters) is None


@pytest.mark.parametrize("value", ["minimal", "low", "high", "xhigh", "none"])
def test_any_level_name_is_taken(value):
    assert reasoning_effort_of({"reasoning_effort": value}) == value


@pytest.mark.parametrize("value", ["HIGH", "a b", 3, ["low"], "x" * 17])
def test_a_malformed_level_is_refused(value):
    with pytest.raises(ValueError, match="level name"):
        reasoning_effort_of({"reasoning_effort": value})


@pytest.mark.parametrize("value", [0, -1, True, "1024", 1.5])
def test_a_budget_must_be_a_positive_integer(value):
    with pytest.raises(ValueError, match="positive integer"):
        reasoning_max_tokens_of({"reasoning_max_tokens": value})


def test_a_level_and_a_budget_together_are_refused():
    with pytest.raises(ValueError, match="not both"):
        check_reasoning({"reasoning_effort": "low", "reasoning_max_tokens": 1024})


def test_a_run_that_sets_reasoning_replaces_the_agents_pair():
    assert reasoning_settings({"reasoning_max_tokens": 2048}, "high", None) == (None, 2048)
    assert reasoning_settings({"topic": "x"}, "high", None) == ("high", None)
