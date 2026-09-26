"""The workspace cap is a policy rule, so it must pass the policy write boundary.

``PUT /dashboard/settings`` wrote the rule straight through the repository. A
negative cap was stored, and from then on every read that compiles the
workspace's rules (effective-policy preview, run start) failed with a 500.
"""

import pytest
from agentarea_api.api.v1.dashboard import WorkspaceSettingsUpdate
from pydantic import ValidationError


@pytest.mark.parametrize("cap", [-1.0, float("inf"), float("nan")])
def test_a_cap_that_cannot_compile_is_invalid_input(cap):
    with pytest.raises(ValidationError):
        WorkspaceSettingsUpdate(monthly_cap_usd=cap)


@pytest.mark.parametrize("cap", [0.0, 250.5, None])
def test_a_cap_the_policy_engine_accepts_is_valid(cap):
    assert WorkspaceSettingsUpdate(monthly_cap_usd=cap).monthly_cap_usd == cap
