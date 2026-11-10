"""Graph migrations: one-shot steps recorded once applied, run by ``agentarea-api migrate``."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from agentarea_common.rebac.graph_migrations import (
    GraphMigration,
    apply_pending_graph_migrations,
)


class _Store:
    """The graph_migrations table, and the sessions a run opens over it."""

    def __init__(self, applied: set[str] = frozenset()) -> None:
        self.applied = set(applied)
        self.recorded: list[str] = []

    @asynccontextmanager
    async def session(self):
        store = self
        pending: list[str] = []

        class _Session:
            async def execute(self, statement):
                if getattr(statement, "is_insert", False):
                    params = statement.compile(dialect=postgresql.dialect()).params
                    pending.append(params["id"])
                    return SimpleNamespace()
                return SimpleNamespace(scalars=lambda: list(store.applied))

            async def commit(self):
                store.applied.update(pending)
                store.recorded.extend(pending)
                pending.clear()

        yield _Session()


def _step(step_id: str, ran: list[str], *, fails: bool = False) -> GraphMigration:
    async def apply(session, graph):
        ran.append(step_id)
        if fails:
            raise RuntimeError(f"{step_id} failed")

    return GraphMigration(id=step_id, description=step_id, apply=apply)


async def _no_graph():
    raise AssertionError("no step asked for the graph")


async def test_pending_steps_run_in_order_and_are_recorded():
    store, ran = _Store(), []

    applied = await apply_pending_graph_migrations(
        store.session, [_step("20260101_0000_a", ran), _step("20260102_0000_b", ran)], _no_graph
    )

    assert ran == ["20260101_0000_a", "20260102_0000_b"]
    assert applied == ["20260101_0000_a", "20260102_0000_b"]
    assert store.recorded == ["20260101_0000_a", "20260102_0000_b"]


async def test_a_recorded_step_does_not_run_again():
    store, ran = _Store({"20260101_0000_a"}), []

    applied = await apply_pending_graph_migrations(
        store.session, [_step("20260101_0000_a", ran), _step("20260102_0000_b", ran)], _no_graph
    )

    assert ran == ["20260102_0000_b"]
    assert applied == ["20260102_0000_b"]


async def test_a_failed_step_raises_is_not_recorded_and_stops_the_run():
    store, ran = _Store(), []
    steps = [
        _step("20260101_0000_a", ran),
        _step("20260102_0000_b", ran, fails=True),
        _step("20260103_0000_c", ran),
    ]

    with pytest.raises(RuntimeError, match="20260102_0000_b failed"):
        await apply_pending_graph_migrations(store.session, steps, _no_graph)

    assert store.recorded == ["20260101_0000_a"]
    assert ran == ["20260101_0000_a", "20260102_0000_b"]


@pytest.mark.parametrize(
    "ids",
    [["20260102_0000_b", "20260101_0000_a"], ["20260101_0000_a", "20260101_0000_a"], ["not-a-date"]],
)
async def test_the_registry_must_be_ordered_unique_and_dated(ids):
    with pytest.raises(ValueError):
        await apply_pending_graph_migrations(
            _Store().session, [_step(i, []) for i in ids], _no_graph
        )
