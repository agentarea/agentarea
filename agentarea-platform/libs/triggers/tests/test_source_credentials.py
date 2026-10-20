"""A reply sender reads its source's credentials in the task's workspace, references resolved."""

import json
from contextlib import asynccontextmanager

import pytest
from agentarea_triggers.channels.exceptions import FatalError, RetryableError
from agentarea_triggers.channels.source_credentials import SourceCredentialReader


class _Secrets:
    def __init__(self, values, *, fail=False):
        self.values = values
        self.fail = fail

    async def get_secret(self, name):
        if self.fail:
            raise ConnectionError("store down")
        return self.values.get(name)


class _Factory:
    def __init__(self, secrets):
        self.secrets = secrets
        self.contexts = []

    def create(self, *, session, user_context):
        self.contexts.append(user_context)
        return self.secrets


def _session_factory():
    @asynccontextmanager
    async def factory():
        yield object()

    return factory


async def _read(secrets, **overrides):
    factory = _Factory(secrets)
    reader = SourceCredentialReader(_session_factory(), factory)
    args = {
        "workspace_id": "ws-1",
        "owner": "u-1",
        "credential_type": "chat",
        "credential_key": "key-1",
        **overrides,
    }
    return await reader(**args), factory


async def test_fields_and_workspace_secret_references_are_resolved():
    secrets = _Secrets(
        {
            "channel_cred:chat:key-1": json.dumps(
                {"bot_token": {"secret_name": "BOT"}, "from_address": "a@x.io"}
            ),
            "BOT": "123:ABC",
        }
    )
    credentials, factory = await _read(secrets)
    assert credentials == {"bot_token": "123:ABC", "from_address": "a@x.io"}
    (context,) = factory.contexts
    assert (context.workspace_id, context.user_id) == ("ws-1", "u-1")


async def test_no_stored_credentials_is_permanent():
    with pytest.raises(FatalError, match="no credentials"):
        await _read(_Secrets({}))


async def test_a_reference_to_an_empty_secret_is_permanent():
    secrets = _Secrets({"channel_cred:chat:key-1": json.dumps({"bot_token": {"secret_name": "X"}})})
    with pytest.raises(FatalError, match="bot_token"):
        await _read(secrets)


async def test_an_unreachable_store_is_retried():
    with pytest.raises(RetryableError):
        await _read(_Secrets({}, fail=True))
