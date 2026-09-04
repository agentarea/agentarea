"""LLM output ceilings must come from the persisted effective policy."""

import pytest
from agentarea_execution.activities.agent_execution_activities import (
    resolve_llm_max_tokens,
)


def _policy(cap: int) -> dict:
    return {"tokens": {"max_tokens_per_call": cap}}


def test_policy_cap_is_required():
    with pytest.raises(ValueError, match=r"tokens\.max_tokens_per_call"):
        resolve_llm_max_tokens(
            requested=None,
            model_cap=4096,
            effective_policy=None,
        )


def test_strictest_request_model_and_policy_cap_wins():
    assert (
        resolve_llm_max_tokens(
            requested=3000,
            model_cap=2000,
            effective_policy=_policy(1000),
        )
        == 1000
    )
    assert (
        resolve_llm_max_tokens(
            requested=500,
            model_cap=2000,
            effective_policy=_policy(1000),
        )
        == 500
    )
