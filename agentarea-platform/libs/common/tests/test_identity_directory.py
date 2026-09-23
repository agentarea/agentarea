"""Tests for resolving member ids into human identities via the Kratos admin API.

The members surface used to render everyone except the caller as a raw
identity id. These tests pin the resolution rules, including the ones that
must *not* invent a value when the directory has nothing to say.
"""

import httpx
import pytest
from agentarea_common.auth.identity_directory import (
    IdentityRecord,
    KratosIdentityDirectory,
    identity_for,
)

ALICE = "11111111-1111-1111-1111-111111111111"
BOB = "22222222-2222-2222-2222-222222222222"


def _directory(handler) -> KratosIdentityDirectory:
    return KratosIdentityDirectory(
        admin_url="http://kratos:4434",
        transport=httpx.MockTransport(handler),
    )


def _identity(identity_id: str, traits: dict) -> httpx.Response:
    return httpx.Response(200, json={"id": identity_id, "traits": traits})


async def test_resolves_email_and_name_from_traits():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/admin/identities/{ALICE}"
        return _identity(
            ALICE,
            {"email": "alice@example.com", "name": {"first": "Alice", "last": "Ng"}},
        )

    resolved = await _directory(handler).resolve([ALICE])

    assert resolved[ALICE] == IdentityRecord(
        user_id=ALICE, email="alice@example.com", display_name="Alice Ng"
    )


async def test_falls_back_to_username_then_email_for_display_name():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(ALICE):
            return _identity(ALICE, {"email": "alice@example.com", "username": "alice"})
        return _identity(BOB, {"email": "bob@example.com"})

    resolved = await _directory(handler).resolve([ALICE, BOB])

    assert resolved[ALICE].display_name == "alice"
    assert resolved[BOB].display_name == "bob@example.com"


async def test_partial_name_traits_do_not_leak_none():
    def handler(_request: httpx.Request) -> httpx.Response:
        return _identity(ALICE, {"email": "alice@example.com", "name": {"first": "Alice"}})

    resolved = await _directory(handler).resolve([ALICE])

    assert resolved[ALICE].display_name == "Alice"


async def test_unknown_identity_is_absent_rather_than_invented():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"message": "Not Found"}})

    resolved = await _directory(handler).resolve([ALICE])

    assert resolved == {}


async def test_directory_failure_degrades_to_unresolved_and_logs(caplog):
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("kratos unreachable")

    with caplog.at_level("WARNING"):
        resolved = await _directory(handler).resolve([ALICE, BOB])

    assert resolved == {}
    assert "identity" in caplog.text.lower()


async def test_one_failure_does_not_discard_the_others():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(ALICE):
            raise httpx.ConnectError("flaky")
        return _identity(BOB, {"email": "bob@example.com"})

    resolved = await _directory(handler).resolve([ALICE, BOB])

    assert set(resolved) == {BOB}


async def test_resolve_deduplicates_and_skips_empty_input():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return _identity(ALICE, {"email": "alice@example.com"})

    directory = _directory(handler)

    assert await directory.resolve([]) == {}
    await directory.resolve([ALICE, ALICE, ALICE])

    assert len(calls) == 1


@pytest.mark.parametrize("admin_url", ["", "   "])
async def test_unconfigured_admin_url_is_rejected_loudly(admin_url):
    with pytest.raises(ValueError, match="admin_url"):
        KratosIdentityDirectory(admin_url=admin_url)


# --------------------------------------------------------------------------
# identity_for — the rule both the REST surface and the toolset share
# --------------------------------------------------------------------------


def test_identity_for_prefers_the_directory():
    resolved = {ALICE: IdentityRecord(ALICE, "alice@example.com", "Alice Ng")}

    identity = identity_for(
        ALICE, resolved, current_user_id=ALICE, current_user_email="stale@token"
    )

    assert identity.display_name == "Alice Ng"
    assert identity.email == "alice@example.com"


def test_identity_for_uses_the_callers_token_for_the_caller():
    identity = identity_for(
        ALICE, {}, current_user_id=ALICE, current_user_email="alice@example.com"
    )

    assert identity.email == "alice@example.com"
    assert identity.display_name == "alice@example.com"


def test_identity_for_never_borrows_the_callers_token_for_someone_else():
    identity = identity_for(BOB, {}, current_user_id=ALICE, current_user_email="alice@example.com")

    assert identity == IdentityRecord(user_id=BOB, email=None, display_name=None)
