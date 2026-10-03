from uuid import uuid4

import pytest
from agentarea_agents.serving.assignment import pick_arm


def test_the_same_key_always_gets_the_same_arm():
    key = str(uuid4())

    assert {pick_arm(key, {"control": 50, "candidate": 50}) for _ in range(20)} == {
        pick_arm(key, {"control": 50, "candidate": 50})
    }


def test_shares_follow_the_weights():
    keys = [str(uuid4()) for _ in range(10_000)]

    candidate = sum(pick_arm(k, {"control": 90, "candidate": 10}) == "candidate" for k in keys)

    assert 800 <= candidate <= 1200


def test_a_zero_weight_arm_never_serves():
    keys = [str(uuid4()) for _ in range(2_000)]

    assert {pick_arm(k, {"control": 100, "candidate": 0}) for k in keys} == {"control"}


def test_weights_must_sum_to_one_hundred():
    with pytest.raises(ValueError, match="100"):
        pick_arm("k", {"control": 60, "candidate": 30})
