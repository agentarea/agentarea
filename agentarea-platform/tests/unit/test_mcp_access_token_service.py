"""Unit tests for MCPAccessTokenService."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from agentarea_mcp.application.access_token_service import (
    MCPAccessTokenService,
    hash_token,
    _TOKEN_PREFIX,
)
from agentarea_mcp.domain.auth_models import MCPAccessToken


def _make_token(
    name: str = "test",
    raw: str = "aat_testtoken",
    is_active: bool = True,
    expires_at: datetime | None = None,
) -> MCPAccessToken:
    record = MagicMock(spec=MCPAccessToken)
    record.id = uuid4()
    record.name = name
    record.token_hash = hash_token(raw)
    record.token_prefix = raw[:12]
    record.is_active = is_active
    record.expires_at = expires_at
    record.is_expired = MagicMock(
        return_value=bool(expires_at and datetime.utcnow() >= expires_at)
    )
    return record


@pytest.fixture
def repo():
    r = MagicMock()
    r.create = AsyncMock()
    r.get_by_id = AsyncMock()
    r.get_by_hash = AsyncMock()
    r.list_all = AsyncMock()
    r.update = AsyncMock()
    r.increment_access_count = AsyncMock()
    return r


@pytest.fixture
def service(repo):
    return MCPAccessTokenService(repo)


# ---------------------------------------------------------------------------
# Token generation helpers
# ---------------------------------------------------------------------------


class TestTokenHelpers:
    def test_hash_is_deterministic(self):
        raw = "aat_sometoken"
        assert hash_token(raw) == hash_token(raw)

    def test_hash_is_64_hex_chars(self):
        assert len(hash_token("anything")) == 64

    def test_different_tokens_have_different_hashes(self):
        assert hash_token("aat_a") != hash_token("aat_b")


# ---------------------------------------------------------------------------
# create_token
# ---------------------------------------------------------------------------


class TestCreateToken:
    @pytest.mark.asyncio
    async def test_returns_record_and_raw_token(self, service, repo):
        stored = _make_token()
        repo.create.return_value = stored

        record, raw = await service.create_token("my-token")

        assert raw.startswith(_TOKEN_PREFIX)
        assert record is stored
        # Repo received kwargs with the correct hash
        kwargs = repo.create.call_args[1]
        assert kwargs["token_hash"] == hash_token(raw)
        assert kwargs["token_prefix"] == raw[:12]

    @pytest.mark.asyncio
    async def test_expiry_set_when_expires_in_days_given(self, service, repo):
        stored = _make_token()
        repo.create.return_value = stored

        await service.create_token("expiring", expires_in_days=7)

        kwargs = repo.create.call_args[1]
        assert kwargs["expires_at"] is not None
        assert kwargs["expires_at"] > datetime.utcnow()

    @pytest.mark.asyncio
    async def test_no_expiry_when_not_given(self, service, repo):
        stored = _make_token()
        repo.create.return_value = stored

        await service.create_token("forever")

        kwargs = repo.create.call_args[1]
        assert kwargs["expires_at"] is None


# ---------------------------------------------------------------------------
# validate_token
# ---------------------------------------------------------------------------


class TestValidateToken:
    @pytest.mark.asyncio
    async def test_valid_token_returns_record(self, service, repo):
        raw = "aat_validtoken"
        record = _make_token(raw=raw)
        repo.get_by_hash.return_value = record

        result = await service.validate_token(raw)

        assert result is record
        repo.get_by_hash.assert_called_once_with(hash_token(raw))

    @pytest.mark.asyncio
    async def test_unknown_token_returns_none(self, service, repo):
        repo.get_by_hash.return_value = None
        result = await service.validate_token("aat_unknown")
        assert result is None

    @pytest.mark.asyncio
    async def test_inactive_token_returns_none(self, service, repo):
        record = _make_token(is_active=False)
        repo.get_by_hash.return_value = record
        result = await service.validate_token("aat_revoked")
        assert result is None

    @pytest.mark.asyncio
    async def test_expired_token_returns_none(self, service, repo):
        past = datetime.utcnow() - timedelta(hours=1)
        record = _make_token(expires_at=past)
        record.is_expired.return_value = True
        repo.get_by_hash.return_value = record

        result = await service.validate_token("aat_expired")
        assert result is None

    @pytest.mark.asyncio
    async def test_future_expiry_is_valid(self, service, repo):
        future = datetime.utcnow() + timedelta(days=1)
        record = _make_token(expires_at=future)
        record.is_expired.return_value = False
        repo.get_by_hash.return_value = record

        result = await service.validate_token("aat_valid")
        assert result is record


# ---------------------------------------------------------------------------
# revoke_token
# ---------------------------------------------------------------------------


class TestRevokeToken:
    @pytest.mark.asyncio
    async def test_revoke_existing_token_returns_true(self, service, repo):
        record = _make_token()
        repo.get_by_id.return_value = record

        result = await service.revoke_token(record.id)

        assert result is True
        repo.update.assert_called_once_with(record.id, is_active=False)

    @pytest.mark.asyncio
    async def test_revoke_missing_token_returns_false(self, service, repo):
        repo.get_by_id.return_value = None
        result = await service.revoke_token(uuid4())
        assert result is False
        repo.update.assert_not_called()


# ---------------------------------------------------------------------------
# list_tokens / get_token
# ---------------------------------------------------------------------------


class TestListAndGet:
    @pytest.mark.asyncio
    async def test_list_returns_all(self, service, repo):
        tokens = [_make_token(name=f"t{i}") for i in range(3)]
        repo.list_all.return_value = tokens

        result = await service.list_tokens()
        assert result == tokens

    @pytest.mark.asyncio
    async def test_get_returns_record(self, service, repo):
        record = _make_token()
        repo.get_by_id.return_value = record

        result = await service.get_token(record.id)
        assert result is record

    @pytest.mark.asyncio
    async def test_get_missing_returns_none(self, service, repo):
        repo.get_by_id.return_value = None
        result = await service.get_token(uuid4())
        assert result is None


# ---------------------------------------------------------------------------
# record_access
# ---------------------------------------------------------------------------


class TestRecordAccess:
    @pytest.mark.asyncio
    async def test_delegates_to_repo(self, service, repo):
        tid = uuid4()
        await service.record_access(tid)
        repo.increment_access_count.assert_called_once_with(tid)
