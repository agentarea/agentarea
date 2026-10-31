"""What an egress exit may say about its proxy, and how an instance names one."""

from uuid import uuid4

import pytest
from agentarea_mcp.schemas.dto import (
    MCPServerCreate,
    MCPServerInstanceCreate,
    MCPServerInstanceUpdate,
)
from agentarea_mcp.schemas.egress_exit_dto import EgressExitCreate, EgressExitUpdate
from pydantic import ValidationError


def _exit(**fields) -> EgressExitCreate:
    return EgressExitCreate.model_validate({"name": "office", **fields})


@pytest.mark.parametrize(
    "url",
    ["http://proxy.example.com:3128", "https://proxy.example.com:443", "socks5://1.2.3.4:1080"],
)
def test_an_upstream_is_scheme_host_and_port(url):
    assert _exit(upstream_url=url).upstream_url == url


@pytest.mark.parametrize(
    "url",
    [
        "ftp://proxy.example.com:21",
        "http://proxy.example.com",
        "http://user:pass@proxy.example.com:3128",
        "http://proxy.example.com:3128/path",
        "http://proxy.example.com:3128?x=1",
        "proxy.example.com:3128",
    ],
)
def test_an_upstream_with_anything_else_is_refused(url):
    with pytest.raises(ValidationError, match="upstream_url"):
        _exit(upstream_url=url)


def test_credentials_to_a_plaintext_proxy_need_an_explicit_opt_in():
    secret = uuid4()
    with pytest.raises(ValidationError, match="unencrypted"):
        _exit(upstream_url="http://p.example.com:3128", username="u", password_secret_id=secret)

    opted = _exit(
        upstream_url="http://p.example.com:3128",
        username="u",
        password_secret_id=secret,
        allow_plaintext_credentials=True,
    )
    assert opted.password_secret_id == secret
    assert _exit(upstream_url="https://p.example.com:443", username="u", password_secret_id=secret)


def test_a_password_needs_a_username():
    with pytest.raises(ValidationError, match="needs a username"):
        _exit(upstream_url="https://p.example.com:443", password_secret_id=uuid4())


def test_an_exit_carries_no_password_value():
    with pytest.raises(ValidationError):
        _exit(upstream_url="https://p.example.com:443", username="u", password="hunter2")


def test_an_update_checks_a_new_upstream_the_same_way():
    with pytest.raises(ValidationError, match="upstream_url"):
        EgressExitUpdate(upstream_url="http://user:pass@p.example.com:3128")
    assert EgressExitUpdate(description="x").model_dump(exclude_unset=True) == {"description": "x"}


def test_an_instance_binds_an_exit_by_id():
    exit_id = str(uuid4())
    update = MCPServerInstanceUpdate(json_spec={"egress_exit": exit_id})
    assert update.json_spec == {"egress_exit": exit_id}
    assert MCPServerInstanceUpdate(json_spec={"egress_exit": None}).json_spec == {
        "egress_exit": None
    }


@pytest.mark.parametrize("value", ["aeza-se", "", 123, {"id": "x"}])
def test_an_instance_naming_an_exit_any_other_way_is_refused(value):
    with pytest.raises(ValidationError, match="egress exit id"):
        MCPServerInstanceCreate(
            name="i", server_spec_id=uuid4(), json_spec={"egress_exit": value}
        )


def test_a_server_spec_cannot_bind_every_instance_to_an_exit():
    with pytest.raises(ValidationError, match="not a server spec"):
        MCPServerCreate(name="s", description="d", json_spec={"egress_exit": str(uuid4())})
