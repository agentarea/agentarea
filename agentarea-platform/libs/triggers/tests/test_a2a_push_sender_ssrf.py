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


@pytest.mark.asyncio
async def test_push_targets_ignore_the_deployments_private_allowances(monkeypatch):
    """A push URL is chosen by an A2A client, not a member: no allowlist, no opt-out."""
    from agentarea_common.config import get_settings

    monkeypatch.setenv("ALLOW_PRIVATE_URLS", "true")
    monkeypatch.setenv("OUTBOUND_PRIVATE_ALLOWLIST", "127.0.0.0/8")
    get_settings.cache_clear()
    try:
        send = make_a2a_webhook_sender(_Reader())
        with pytest.raises(FatalError, match="unsafe push webhook url"):
            await send(
                {"url": "http://127.0.0.1:6379/", "task_id": "t", "config_id": "c"},
                '{"status": "done"}',
            )
    finally:
        get_settings.cache_clear()
