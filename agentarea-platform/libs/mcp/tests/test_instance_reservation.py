"""A hosted MCP instance's reservation, read from the manager for price estimates."""

from decimal import Decimal

import pytest
from agentarea_mcp.instance_reservation import (
    InstanceReservation,
    InstanceReservationReader,
    parse_reservation,
)


def test_the_manager_answer_reads_as_vcpu_and_gib():
    assert parse_reservation({"cpu_millicores": 100, "memory_bytes": 128 * 1024**2}) == (
        InstanceReservation(vcpu=Decimal("0.1"), memory_gib=Decimal("0.125"))
    )


def test_a_reservation_of_nothing_is_none():
    assert parse_reservation({"cpu_millicores": 0, "memory_bytes": 0}) is None


@pytest.mark.parametrize(
    "body",
    [[], {"cpu_millicores": "100m", "memory_bytes": 1}, {"cpu_millicores": -1, "memory_bytes": 1}],
)
def test_a_malformed_answer_is_refused(body):
    with pytest.raises(ValueError, match="reservation is not"):
        parse_reservation(body)


async def test_the_reservation_is_reread_only_after_its_ttl_and_a_failure_is_retried():
    now = [0.0]
    answers = [InstanceReservation(Decimal(1), Decimal(1)), RuntimeError("down")]
    calls = []

    async def fetch():
        calls.append(now[0])
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    reader = InstanceReservationReader(fetch=fetch, clock=lambda: now[0])

    assert await reader.get() == InstanceReservation(Decimal(1), Decimal(1))
    now[0] = 100
    assert await reader.get() == InstanceReservation(Decimal(1), Decimal(1))
    now[0] = 400
    # An unreachable manager leaves the reservation unknown rather than stale.
    assert await reader.get() is None
    assert calls == [0.0, 400]
