"""A payload the domain model would reject must be rejected at the request boundary.

The domain ``TriggerCreate`` requires a cron expression for cron triggers; the
request DTO did not, so ``to_domain`` raised inside the handler and the API
answered 500 instead of 422.
"""

from uuid import uuid4

import pytest
from agentarea_triggers.schemas.dto import TriggerCreate
from pydantic import ValidationError


def test_a_cron_trigger_without_an_expression_is_invalid_input():
    with pytest.raises(ValidationError, match="cron_expression"):
        TriggerCreate(name="nightly", agent_id=uuid4(), trigger_type="cron")


def test_a_cron_trigger_with_an_expression_reaches_the_domain():
    payload = TriggerCreate(
        name="nightly", agent_id=uuid4(), trigger_type="cron", cron_expression="0 3 * * *"
    )

    assert payload.to_domain(created_by="user-1").cron_expression == "0 3 * * *"
