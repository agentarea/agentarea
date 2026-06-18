"""Guard: keep the executable main-flow registry honest.

Runs in the full suite (`make test`), where all flow-marked tests are collected.

  - Every `MainFlow` must have a `@pytest.mark.flow` test, unless it is a tracked
    gap in `PENDING_COVERAGE`. Adding a flow without either fails CI.
  - A flow that gains a test may NOT stay in `PENDING_COVERAGE` (ratchet): once
    covered, it must be promoted out of the pending set.
"""

import pytest

from agentarea_common.testing.flows import COVERED_FLOWS, PENDING_COVERAGE, MainFlow


def test_every_main_flow_has_a_marked_test():
    if not COVERED_FLOWS:
        pytest.skip(
            "No flow-marked tests collected in this session "
            "(run the full suite via `make test` or `pytest -m flow`)."
        )
    declared = {f.value for f in MainFlow}
    pending = {f.value for f in PENDING_COVERAGE}

    missing = declared - COVERED_FLOWS - pending
    assert not missing, (
        f"Main flows with no @pytest.mark.flow test: {sorted(missing)}. "
        "Add a canonical test, or list the flow in PENDING_COVERAGE with a reason."
    )


def test_pending_flows_are_actually_uncovered():
    """Ratchet: a flow that now has a test must be removed from PENDING_COVERAGE."""
    if not COVERED_FLOWS:
        pytest.skip("No flow-marked tests collected in this session.")
    pending = {f.value for f in PENDING_COVERAGE}
    wrongly_pending = pending & COVERED_FLOWS
    assert not wrongly_pending, (
        f"These flows now have a test; remove them from PENDING_COVERAGE: "
        f"{sorted(wrongly_pending)}."
    )
