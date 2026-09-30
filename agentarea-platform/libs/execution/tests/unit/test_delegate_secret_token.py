"""The bearer for a remote delegate is read from the workspace secret at call time."""

import pytest
from agentarea_execution.activities.agent.tools import _secret_token_provider


class _Secrets:
    def __init__(self, values: dict[str, str]):
        self.values = values
        self.reads: list[str] = []

    async def get_secret(self, secret_name: str) -> str | None:
        self.reads.append(secret_name)
        return self.values.get(secret_name)


@pytest.mark.asyncio
async def test_reads_the_secret_only_when_called():
    secrets = _Secrets({"aadocs-key": "aat_123"})

    resolve = _secret_token_provider(secrets, "aadocs-key")
    assert secrets.reads == []

    assert await resolve() == "aat_123"
    assert secrets.reads == ["aadocs-key"]


@pytest.mark.asyncio
async def test_a_missing_secret_is_an_error_naming_it():
    resolve = _secret_token_provider(_Secrets({}), "aadocs-key")

    with pytest.raises(LookupError, match="aadocs-key"):
        await resolve()
