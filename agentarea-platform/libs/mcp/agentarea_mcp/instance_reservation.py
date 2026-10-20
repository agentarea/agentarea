"""What a hosted MCP instance reserves, as the MCP manager that runs it reports.

The manager (or the data plane behind it) sets a new instance's requests and limits;
compute billing charges for the request, else the limit. The platform only reads that
figure to show a hosted connector's expected price, so it never keeps a copy of the
manager's resource configuration that could drift from what is actually reserved.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import cast

from agentarea_common.config import get_settings
from agentarea_common.outbound import Destination, outbound_client

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 3.0
# The reservation changes only with the manager's configuration, i.e. on a deploy.
_TTL_SECONDS = 300.0
# After a failure, so an unreachable manager costs one request per interval rather
# than one per catalog page.
_RETRY_AFTER_SECONDS = 30.0

_MILLICORES_PER_VCPU = Decimal(1000)
_BYTES_PER_GIB = Decimal(1024**3)


@dataclass(frozen=True)
class InstanceReservation:
    """What one running instance holds on its host, whether busy or idle."""

    vcpu: Decimal
    memory_gib: Decimal


def parse_reservation(body: object) -> InstanceReservation | None:
    """The manager's answer as vCPU and GiB, or None for one that reserves nothing."""
    if not isinstance(body, dict):
        raise ValueError(f"reservation is not an object: {body!r}")
    data = cast("dict[str, object]", body)
    millicores = _quantity(data, "cpu_millicores")
    memory_bytes = _quantity(data, "memory_bytes")
    if not millicores and not memory_bytes:
        return None
    return InstanceReservation(
        vcpu=Decimal(millicores) / _MILLICORES_PER_VCPU,
        memory_gib=Decimal(memory_bytes) / _BYTES_PER_GIB,
    )


def _quantity(body: dict[str, object], key: str) -> int:
    value = body.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"reservation is not a pair of non-negative integers: {body!r}")
    return value


async def _fetch() -> InstanceReservation | None:
    settings = get_settings().mcp
    async with outbound_client(Destination.INTERNAL, timeout=_TIMEOUT_SECONDS) as client:
        response = await client.get(
            f"{settings.MANAGER_URL.rstrip('/')}/instances/reservation",
            headers=settings.manager_inspection_headers(),
        )
        response.raise_for_status()
    return parse_reservation(response.json())


class InstanceReservationReader:
    """The reservation, re-read at most once per TTL; None while it is unknown."""

    def __init__(
        self,
        fetch: Callable[[], Awaitable[InstanceReservation | None]] = _fetch,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._fetch = fetch
        self._clock = clock
        self._value: InstanceReservation | None = None
        self._next_read_at = 0.0

    async def get(self) -> InstanceReservation | None:
        if self._clock() < self._next_read_at:
            return self._value
        try:
            self._value = await self._fetch()
        except Exception:
            logger.warning("MCP manager did not report an instance reservation", exc_info=True)
            self._value = None
            self._next_read_at = self._clock() + _RETRY_AFTER_SECONDS
            return None
        self._next_read_at = self._clock() + _TTL_SECONDS
        return self._value


_reader = InstanceReservationReader()


async def instance_reservation() -> InstanceReservation | None:
    """What a new hosted MCP instance reserves, or None while the manager cannot say."""
    return await _reader.get()
