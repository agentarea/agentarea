"""A2A push delivery goes only to public addresses, through the pinned client."""

import pytest
from agentarea_triggers.channels.adapters import make_a2a_webhook_sender
from agentarea_triggers.channels.exceptions import FatalError


class _Reader:
    async def get_secret(self, name: str) -> str | None:
        return "push-token"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    ["http://169.254.169.254/latest/meta-data/", "http://127.0.0.1:6379/", "http://[::1]/hook"],
)
async def test_a_push_to_a_non_public_address_is_refused_without_retry(url):
    send = make_a2a_webhook_sender(_Reader())

    with pytest.raises(FatalError, match="unsafe push webhook url"):
        await send({"url": url, "task_id": "t", "config_id": "c"}, '{"status": "done"}')
