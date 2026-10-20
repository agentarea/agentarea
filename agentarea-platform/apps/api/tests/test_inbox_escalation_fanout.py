"""An inbox load asks Temporal about a bounded number of waiting tasks at a time."""

import asyncio

import pytest
from agentarea_api.api.v1 import inbox

from .test_inbox_approvals import _escalation, _task, client, session, workflows  # noqa: F401


class _Counting:
    def __init__(self):
        self.in_flight = 0
        self.most = 0

    async def get_pending_escalations(self, execution_id: str) -> list[dict]:
        self.in_flight += 1
        self.most = max(self.most, self.in_flight)
        await asyncio.sleep(0.01)
        self.in_flight -= 1
        return [_escalation(f"esc-{execution_id}", "deploy")]


@pytest.mark.asyncio
async def test_concurrent_escalation_queries_never_exceed_the_bound(client, session, workflows):  # noqa: F811
    counting = _Counting()
    workflows.get_pending_escalations = counting.get_pending_escalations
    for n in range(inbox.ESCALATION_QUERY_CONCURRENCY * 4):
        _task(session, "waiting_for_approval", f"Deploy {n}")
    await session.commit()

    response = await client.get("/v1/workspaces/acme/inbox/?status=waiting_for_approval")

    assert response.status_code == 200, response.text
    assert all(item["escalation_id"] for item in response.json()["items"])
    assert 1 < counting.most <= inbox.ESCALATION_QUERY_CONCURRENCY


@pytest.mark.asyncio
async def test_a_page_is_at_most_the_bound(client):  # noqa: F811
    response = await client.get(
        f"/v1/workspaces/acme/inbox/?page_size={inbox.MAX_INBOX_PAGE_SIZE + 1}"
    )

    assert response.status_code == 422
