"""A workspace registry's source is a member-supplied URL (ADR-0044).

Any self-signup user administers their own workspace, so the index URL they
give is fetched only from a public https host, through the pinned client that
re-checks every redirect hop, within a body cap, a deadline and an item cap,
and parsed as JSON or alias-free YAML. Nothing of a failed fetch or parse comes
back in the error: the stored and returned message is a classification.
"""

import asyncio

import httpx
import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.utils.url_safety import OutboundPolicy, SafeOutboundTransport
from agentarea_registry.application import service as service_module
from agentarea_registry.application.service import (
    RegistryService,
    sync_error_message,
    validate_registry_source,
)
from agentarea_registry.domain.models import Registry
from agentarea_registry.infrastructure.repository import RegistryItemRepository, RegistryRepository

WORKSPACE = {"scope": "workspace", "workspace_id": "acme", "mode": "upstream", "trust": "private"}
PLATFORM = {"scope": "platform", "workspace_id": None, "mode": "mirror", "trust": "official"}
INDEX = "https://index.example/skills.json"
HOSTS = {
    "index.example": "93.184.216.34",
    "metadata.example": "169.254.169.254",
    "openfga": "10.43.0.12",
}


def _check(source_type="url", source_url=INDEX, **fields):
    validate_registry_source(
        registry_type="skills", source_type=source_type, source_url=source_url, **fields
    )


@pytest.mark.parametrize(
    "source_url",
    [
        "/app/.env",
        "/proc/self/environ",
        "file:///etc/passwd",
        "http://index.example/skills.json",
        "https://169.254.169.254/latest/meta-data/",
        "https://metadata.example/skills.json",
        "https://openfga:8080/stores",
        "https://127.0.0.1/skills.json",
    ],
)
def test_a_workspace_index_is_a_public_https_url(source_url):
    with pytest.raises(ValueError, match="public https"):
        _check(source_url=source_url, **WORKSPACE)


def test_a_public_https_index_is_accepted():
    _check(**WORKSPACE)


def test_the_platform_manifest_may_still_name_a_local_file():
    _check(source_url="/app/data/registries/skills.json", **PLATFORM)


@pytest.mark.parametrize("source_url", ["acme/..", "acme/.", "acme/skills\n", "-acme/skills"])
def test_a_github_repository_is_exactly_owner_slash_repo(source_url):
    with pytest.raises(ValueError, match="owner/repo"):
        _check(source_type="github", source_url=source_url, **WORKSPACE)


@pytest.mark.parametrize("ref", ["../main", "-main", "a..b", "main\n", "a b", "/main", "x" * 256])
def test_a_github_ref_is_a_plain_ref(ref):
    with pytest.raises(ValueError, match="source_ref"):
        _check(source_type="github", source_url="acme/skills", source_ref=ref, **WORKSPACE)


@pytest.mark.parametrize("path", ["../x", "a/./b", "a/../b", "a\\b", "a\x00b", "a//b"])
def test_a_github_path_is_a_plain_relative_path(path):
    with pytest.raises(ValueError, match="source_path"):
        _check(source_type="github", source_url="acme/skills", source_path=path, **WORKSPACE)


def test_a_plain_ref_and_path_are_accepted():
    _check(
        source_type="github",
        source_url="acme/skills",
        source_ref="release/v1.2",
        source_path="skills/public",
        **WORKSPACE,
    )


# ── Fetching ──


async def _resolve(host: str, _port: int) -> list[str]:
    return [HOSTS[host]]


def _transport(handler):
    def make() -> httpx.AsyncBaseTransport:
        return SafeOutboundTransport(
            OutboundPolicy(), resolve=_resolve, inner=lambda **_: httpx.MockTransport(handler)
        )

    return make


async def _registry(db_session, url=INDEX) -> Registry:
    registry = Registry(
        name="acme-index",
        registry_type="skills",
        source_type="url",
        source_url=url,
        scope="workspace",
        workspace_id="acme",
        mode="upstream",
        trust="private",
    )
    db_session.add(registry)
    await db_session.commit()
    return registry


def _service(db_session, handler) -> RegistryService:
    context = UserContext(user_id="u", workspace_id="acme")
    return RegistryService(
        RegistryRepository(db_session, context),
        RegistryItemRepository(db_session, context),
        server_repo=None,  # type: ignore[arg-type]
        untrusted_transport=_transport(handler),
    )


def _serving(body: bytes, **headers):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(200)
        return httpx.Response(200, content=body, headers=headers)

    return handler


async def _sync_error(db_session, handler, url=INDEX) -> tuple[Exception, Registry]:
    registry = await _registry(db_session, url)
    service = _service(db_session, handler)
    with pytest.raises(Exception) as raised:
        await service.sync_registry(registry.id)
    await db_session.refresh(registry)
    return raised.value, registry


async def test_a_workspace_index_is_fetched_through_the_pinned_client(db_session, monkeypatch):
    def no_urllib(*_args, **_kwargs):
        raise AssertionError("a workspace source never reaches urllib or open()")

    monkeypatch.setattr(RegistryService, "_fetch_source", staticmethod(no_urllib))
    body = b'{"skills": [{"name": "pdf", "content": "# PDF"}]}'

    stats = await _service(db_session, _serving(body)).sync_registry(
        (await _registry(db_session)).id
    )

    assert stats["new_specs"] == 1


async def test_a_redirect_to_an_internal_host_is_refused(db_session):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "https://metadata.example/latest"})

    error, registry = await _sync_error(db_session, handler)

    assert registry.last_sync_error == "the source could not be reached"
    assert "169.254" not in str(registry.last_sync_error)
    assert sync_error_message(error) == "the source could not be reached"


async def test_a_body_over_the_cap_is_refused(db_session, monkeypatch):
    monkeypatch.setattr(service_module, "MAX_SOURCE_BYTES", 1024)

    _, registry = await _sync_error(db_session, _serving(b'{"skills": []}' + b" " * 2048))

    assert registry.last_sync_error == "the source is larger than 1 KB"


async def test_a_trickling_source_hits_the_deadline(db_session, monkeypatch):
    monkeypatch.setattr(service_module, "SOURCE_DEADLINE_SECONDS", 0.2)

    class Trickle(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(50):
                await asyncio.sleep(0.05)
                yield b" "

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(200)
        return httpx.Response(200, stream=Trickle())

    _, registry = await _sync_error(db_session, handler)

    assert registry.last_sync_error == "the source took longer than 0.2 s to read"


async def test_yaml_aliases_are_refused(db_session):
    body = b'a: &a ["x","x","x"]\nb: &b [*a,*a,*a]\nskills: [*b]\n'

    _, registry = await _sync_error(db_session, _serving(body, **{"content-type": "text/yaml"}))

    assert registry.last_sync_error == "the source is not a valid JSON or YAML index"


async def test_an_index_over_the_item_cap_is_refused(db_session, monkeypatch):
    monkeypatch.setattr(service_module, "MAX_SOURCE_ITEMS", 3)
    body = b'{"skills": [' + b",".join(b'{"name": "s%d"}' % i for i in range(4)) + b"]}"

    _, registry = await _sync_error(db_session, _serving(body))

    assert registry.last_sync_error == "the source lists more than 3 items"


async def test_a_parse_error_never_echoes_the_source(db_session):
    body = b"AGENTAREA_DB_PASSWORD=hunter2: x\n  - : ]["

    error, registry = await _sync_error(db_session, _serving(body))

    assert registry.last_sync_error == "the source is not a valid JSON or YAML index"
    assert "hunter2" not in sync_error_message(error)


async def test_an_unexpected_failure_is_not_echoed(db_session):
    def handler(request: httpx.Request) -> httpx.Response:
        raise RuntimeError("postgres://admin:hunter2@db/internal")

    _, registry = await _sync_error(db_session, handler)

    assert "hunter2" not in str(registry.last_sync_error)


def test_inline_source_urls_are_https_only():
    items = RegistryService._parse_skills(
        {
            "skills": [
                {"name": "a", "content": "x", "source_url": "javascript:alert(1)"},
                {"name": "b", "content": "x", "source_url": "https://github.com/o/r"},
            ]
        }
    )

    assert [item["spec"].get("source_url") for item in items] == [None, "https://github.com/o/r"]


async def test_a_workspace_sync_has_a_deadline_of_its_own(db_session, monkeypatch):
    # The reconcile syncs every workspace's registries one after another; one
    # that never finishes must not hold up the rest.
    monkeypatch.setattr(service_module, "WORKSPACE_SYNC_DEADLINE_SECONDS", 0.2)

    class Stalled:
        async def head(self, repo, ref):
            await asyncio.sleep(5)

    registry = Registry(
        name="acme-repo",
        registry_type="skills",
        source_type="github",
        source_url="acme/skills",
        scope="workspace",
        workspace_id="acme",
        mode="upstream",
        trust="private",
    )
    db_session.add(registry)
    await db_session.commit()
    context = UserContext(user_id="u", workspace_id="acme")
    service = RegistryService(
        RegistryRepository(db_session, context),
        RegistryItemRepository(db_session, context),
        server_repo=None,  # type: ignore[arg-type]
        github_source_factory=lambda _token: Stalled(),  # type: ignore[arg-type,return-value]
    )

    with pytest.raises(service_module.RegistrySyncError, match="longer than 0.2 s"):
        await service.sync_registry(registry.id)
    await db_session.refresh(registry)
    assert registry.last_sync_error == "the sync took longer than 0.2 s"
