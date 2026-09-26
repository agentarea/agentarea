"""A per-token cost must fit the NUMERIC(20, 12) column it is stored in.

Anything at or above 10^8 overflowed at INSERT and answered 500.
"""

from uuid import uuid4

import pytest
from agentarea_api.api.v1.model_specs import ModelSpecCreate, ModelSpecUpdate
from pydantic import ValidationError


def _create(**costs):
    return ModelSpecCreate(
        provider_spec_id=uuid4(),
        model_name="m",
        display_name="M",
        context_window=8192,
        **{"input_cost_per_token": "0", "output_cost_per_token": "0", **costs},
    )


@pytest.mark.parametrize("field", ["input_cost_per_token", "output_cost_per_token"])
@pytest.mark.parametrize("cost", ["100000000", "1e30"])
def test_a_cost_the_column_cannot_hold_is_invalid_input(field, cost):
    with pytest.raises(ValidationError):
        _create(**{field: cost})
    with pytest.raises(ValidationError):
        ModelSpecUpdate(**{field: cost})


def test_the_largest_cost_the_column_holds_is_accepted():
    spec = _create(input_cost_per_token="99999999.999999999999")

    assert str(spec.input_cost_per_token) == "99999999.999999999999"
