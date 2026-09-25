"""The pinned outbound client: every hop, redirects included, lands on a vetted address."""

import httpx
import pytest
from agentarea_common.config import get_settings
from agentarea_common.utils.url_safety import (
    OutboundPolicy,
    SafeOutboundTransport,
    UnsafeUrlError,
)


def _resolver(table: dict[str, list[str]]):
    async def resolve(host: str, port: int) -> list[str]:
        return table[host]

    return resolve


def _client(table, handler, policy=None, **kwargs) -> httpx.AsyncClient:
    transport = SafeOutboundTransport(
        policy=policy or OutboundPolicy(),
        resolve=_resolver(table),
        inner=lambda: httpx.MockTransport(handler),
    )
    return httpx.AsyncClient(transport=transport, **kwargs)


async def test_a_public_host_is_fetched_at_the_address_it_was_vetted_at():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    async with _client({"api.example.com": ["93.184.216.34"]}, handler) as client:
        response = await client.get("https://api.example.com/v1/models?x=1")

    assert response.status_code == 200
    (pinned,) = seen
    assert pinned.url.host == "93.184.216.34"
    assert pinned.url.path == "/v1/models"
    assert pinned.url.query == b"x=1"
    assert pinned.headers["host"] == "api.example.com"
    assert pinned.extensions["sni_hostname"] == "api.example.com"
    # Redirect handling keeps working from the name, not the pinned address.
    assert response.request.url.host == "api.example.com"


async def test_a_name_resolving_to_a_private_address_is_refused():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not connect")

    async with _client({"internal.example.com": ["10.1.2.3"]}, handler) as client:
        with pytest.raises(UnsafeUrlError):
            await client.get("https://internal.example.com/")


async def test_a_name_with_any_private_address_is_refused():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not connect")

    table = {"mixed.example.com": ["93.184.216.34", "127.0.0.1"]}
    async with _client(table, handler) as client:
        with pytest.raises(UnsafeUrlError):
            await client.get("http://mixed.example.com/")


async def test_a_redirect_to_the_metadata_endpoint_is_refused():
    hops: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hops.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})

    table = {"public.example.com": ["93.184.216.34"]}
    async with _client(table, handler, follow_redirects=True) as client:
        with pytest.raises(UnsafeUrlError):
            await client.get("https://public.example.com/.well-known/oauth-authorization-server")

    assert hops == ["https://93.184.216.34/.well-known/oauth-authorization-server"]


async def test_a_redirect_to_a_name_that_resolves_private_is_refused():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(307, headers={"location": "https://rebind.example.com/x"})

    table = {"public.example.com": ["93.184.216.34"], "rebind.example.com": ["10.0.0.7"]}
    async with _client(table, handler, follow_redirects=True) as client:
        with pytest.raises(UnsafeUrlError):
            await client.get("https://public.example.com/")


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "169.254.169.254", "0.0.0.0", "::1", "fd00:ec2::254", "::ffff:a9fe:a9fe"],
)
async def test_ip_literals_in_blocked_ranges_are_refused(address):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not connect")

    host = f"[{address}]" if ":" in address else address
    async with _client({}, handler) as client:
        with pytest.raises(UnsafeUrlError):
            await client.get(f"http://{host}/")


async def test_non_http_schemes_are_refused():
    async with _client({}, lambda r: httpx.Response(200)) as client:
        with pytest.raises(UnsafeUrlError):
            await client.get("ftp://files.example.com/x")


@pytest.mark.parametrize(
    ("entry", "host", "address"),
    [
        ("localhost", "localhost", "127.0.0.1"),
        ("ollama.ai.svc.cluster.local", "ollama.ai.svc.cluster.local", "10.43.0.12"),
        ("192.168.1.0/24", "nas.lan", "192.168.1.50"),
    ],
)
async def test_an_allowlisted_private_destination_is_reachable(entry, host, address):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    policy = OutboundPolicy(private_allowlist=(entry,))
    async with _client({host: [address]}, handler, policy=policy) as client:
        response = await client.get(f"http://{host}:11434/api/tags")

    assert response.status_code == 200
    assert seen[0].url.host == address


async def test_the_allowlist_does_not_open_other_private_destinations():
    policy = OutboundPolicy(private_allowlist=("localhost",))
    async with _client(
        {"meta.example.com": ["169.254.169.254"]}, lambda r: httpx.Response(200), policy=policy
    ) as client:
        with pytest.raises(UnsafeUrlError):
            await client.get("http://meta.example.com/")


@pytest.fixture
def fresh_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_the_allowlist_is_read_from_settings(monkeypatch, fresh_settings):
    monkeypatch.setenv("OUTBOUND_PRIVATE_ALLOWLIST", " localhost , 10.43.0.0/16 ,")

    policy = OutboundPolicy.from_env()

    assert policy.private_allowlist == ("localhost", "10.43.0.0/16")


def test_the_policy_comes_from_the_cached_settings(monkeypatch, fresh_settings):
    monkeypatch.setenv("OUTBOUND_PRIVATE_ALLOWLIST", "localhost")
    first = OutboundPolicy.from_env()
    monkeypatch.setenv("OUTBOUND_PRIVATE_ALLOWLIST", "nas.lan")

    assert OutboundPolicy.from_env() == first


@pytest.fixture
def no_env_proxy(monkeypatch):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)


def _recording_transport(table, pools: list[tuple[str | None, list[httpx.Request]]]):
    def make_pool(proxy: str | None = None) -> httpx.MockTransport:
        seen: list[httpx.Request] = []
        pools.append((proxy, seen))

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200)

        return httpx.MockTransport(handler)

    return SafeOutboundTransport(policy=OutboundPolicy(), resolve=_resolver(table), inner=make_pool)


async def test_a_proxied_destination_is_vetted_then_sent_by_name_through_the_proxy(
    monkeypatch, no_env_proxy
):
    monkeypatch.setenv("HTTPS_PROXY", "http://egress.corp:3128")
    pools: list[tuple[str | None, list[httpx.Request]]] = []
    transport = _recording_transport({"api.example.com": ["93.184.216.34"]}, pools)

    async with httpx.AsyncClient(transport=transport) as client:
        await client.get("https://api.example.com/v1")

    ((proxy, seen),) = pools
    assert proxy == "http://egress.corp:3128"
    assert seen[0].url.host == "api.example.com"


async def test_a_proxied_destination_resolving_private_is_still_refused(monkeypatch, no_env_proxy):
    monkeypatch.setenv("HTTPS_PROXY", "http://egress.corp:3128")
    pools: list[tuple[str | None, list[httpx.Request]]] = []
    transport = _recording_transport({"internal.example.com": ["10.0.0.9"]}, pools)

    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(UnsafeUrlError):
            await client.get("https://internal.example.com/")

    assert pools == []


async def test_no_proxy_keeps_the_direct_pinned_connection(monkeypatch, no_env_proxy):
    monkeypatch.setenv("HTTPS_PROXY", "http://egress.corp:3128")
    monkeypatch.setenv("NO_PROXY", "api.example.com")
    pools: list[tuple[str | None, list[httpx.Request]]] = []
    transport = _recording_transport({"api.example.com": ["93.184.216.34"]}, pools)

    async with httpx.AsyncClient(transport=transport) as client:
        await client.get("https://api.example.com/v1")

    ((proxy, seen),) = pools
    assert proxy is None
    assert seen[0].url.host == "93.184.216.34"


async def test_two_names_on_one_address_never_share_a_connection_pool():
    """Pooling by the pinned IP would hand the second name the first name's TLS session."""
    pools: list[list[httpx.Request]] = []

    def make_pool() -> httpx.MockTransport:
        seen: list[httpx.Request] = []
        pools.append(seen)

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200)

        return httpx.MockTransport(handler)

    transport = SafeOutboundTransport(
        policy=OutboundPolicy(),
        resolve=_resolver({"a.example.com": ["93.184.216.34"], "b.example.com": ["93.184.216.34"]}),
        inner=make_pool,
    )
    async with httpx.AsyncClient(transport=transport) as client:
        await client.get("https://a.example.com/")
        await client.get("https://b.example.com/")
        await client.get("https://a.example.com/again")

    assert len(pools) == 2
    assert [r.extensions["sni_hostname"] for r in pools[0]] == ["a.example.com"] * 2
    assert [r.extensions["sni_hostname"] for r in pools[1]] == ["b.example.com"]


def test_an_invalid_allowlist_entry_fails_loudly():
    with pytest.raises(ValueError):
        OutboundPolicy(private_allowlist=("10.0.0.0/33",))
