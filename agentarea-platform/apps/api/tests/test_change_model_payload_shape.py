"""The change_model payload must carry everything the resolved model carries.

There are two places that build a "ResolvedModelInfo-compatible" dict: the worker's
resolve-model activity, which builds it from the model class, and
``agents_tasks._resolve_model_info``, which builds it by hand for the change_model
signal. Only the first is type-checked against ResolvedModelInfo.

So a field added to the model reaches the handwritten dict only if somebody
remembers. When it does not, nothing fails — ChangeModelPayload fills in the
default, and the run continues under it. For ``managed_by`` the default is "the
customer's own key", which on a platform model means we pay for the calls and the
entitlement check goes back to failing open. A switch to a platform model mid-run
would have done exactly that.
"""

import inspect

from agentarea_api.api.v1 import agents_tasks
from agentarea_execution.models import ChangeModelPayload, ResolvedModelInfo

# Fields the handwritten dict is not expected to carry.
#
# resolved_at is stamped by whoever builds the payload rather than read from the
# model, and both builders set it. Everything else on ResolvedModelInfo describes
# the model and must survive a switch.
_NOT_FROM_THE_MODEL: set[str] = set()


def _keys_built_by_hand() -> set[str]:
    """The literal keys of the dict ``_resolve_model_info`` returns.

    Read from the source rather than by calling it, because calling it needs a
    database, a service and a loaded instance — none of which this is about. The
    question here is only which keys the function is written to produce.
    """
    source = inspect.getsource(agents_tasks._resolve_model_info)
    return {
        line.split('"')[1]
        for line in source.splitlines()
        if line.strip().startswith('"') and '":' in line
    }


def test_the_handwritten_payload_carries_every_model_field():
    expected = set(ResolvedModelInfo.model_fields) - _NOT_FROM_THE_MODEL
    missing = expected - _keys_built_by_hand()
    assert not missing, (
        "agents_tasks._resolve_model_info does not set "
        f"{sorted(missing)}. A change_model signal would leave "
        "them at their defaults for the rest of the run."
    )


def test_managed_by_specifically():
    """Named on its own because its default is the expensive one.

    The generic check above would catch this too, but only while ResolvedModelInfo
    still declares the field. This says out loud that the payload has to answer
    "whose credentials" — so deleting it from both places at once is a deliberate
    act rather than a tidy-up.
    """
    assert "managed_by" in _keys_built_by_hand()
    assert "managed_by" in ChangeModelPayload.model_fields
