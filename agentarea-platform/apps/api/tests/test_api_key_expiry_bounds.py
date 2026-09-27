"""An API key's expiry is bounded, as an OAuth link's is.

Unbounded, a large ``expires_in_days`` overflowed ``timedelta`` inside token
creation and came back as a 500 (found by the live-stack OpenAPI fuzz).
"""

import pytest
from agentarea_api.api.v1.api_keys import APIKeyCreateRequest
from pydantic import ValidationError


@pytest.mark.parametrize("days", [0, 3651, 7125212950461010829])
def test_an_expiry_outside_ten_years_is_refused(days: int) -> None:
    with pytest.raises(ValidationError):
        APIKeyCreateRequest(name="ci", expires_in_days=days)


@pytest.mark.parametrize("days", [None, 1, 3650])
def test_an_expiry_within_ten_years_is_accepted(days: int | None) -> None:
    assert APIKeyCreateRequest(name="ci", expires_in_days=days).expires_in_days == days
