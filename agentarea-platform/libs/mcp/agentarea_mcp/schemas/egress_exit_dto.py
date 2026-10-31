"""Egress exit DTOs: what a member sends to define the proxy an MCP instance leaves through."""

from __future__ import annotations

from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

UPSTREAM_SCHEMES = frozenset({"http", "https", "socks5"})
# socks5 carries the username and password in one byte of length each.
MAX_CREDENTIAL_BYTES = 255


def validate_upstream_url(url: str) -> str:
    """``scheme://host:port`` and nothing else: credentials travel by reference."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as e:
        raise ValueError("upstream_url must be scheme://host:port") from e
    if parts.scheme not in UPSTREAM_SCHEMES:
        raise ValueError("upstream_url scheme must be http, https or socks5")
    if parts.username is not None or parts.password is not None:
        raise ValueError(
            "upstream_url must not carry credentials; set username and password_secret_id"
        )
    if not parts.hostname or port is None:
        raise ValueError("upstream_url needs an explicit host:port")
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise ValueError("upstream_url must be scheme://host:port with no path, query or fragment")
    return f"{parts.scheme}://{parts.netloc}"


def credential_errors(
    *,
    upstream_url: str | None,
    username: str | None,
    password_secret_id: UUID | None,
    allow_plaintext_credentials: bool,
) -> list[str]:
    """What the egress proxy would refuse about these credentials, said at save time."""
    errors: list[str] = []
    if password_secret_id is not None and not username:
        errors.append("password_secret_id needs a username")
    if (username or password_secret_id) and upstream_url is None:
        errors.append("credentials need an upstream_url")
    if (
        (username or password_secret_id)
        and upstream_url is not None
        and urlsplit(upstream_url).scheme != "https"
        and not allow_plaintext_credentials
    ):
        errors.append(
            "credentials to an http or socks5 proxy travel unencrypted; "
            "use https or set allow_plaintext_credentials"
        )
    return errors


class EgressExitCreate(BaseModel):
    """A proxy of the workspace's own that its MCP instances may leave through."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255, description="Name, unique in the workspace.")
    description: str | None = Field(default=None, description="What this exit is for.")
    upstream_url: str = Field(
        max_length=512,
        description="The proxy as scheme://host:port: http, https or socks5, no credentials.",
    )
    username: str | None = Field(
        default=None,
        max_length=MAX_CREDENTIAL_BYTES,
        description="Proxy username, if it needs one.",
    )
    password_secret_id: UUID | None = Field(
        default=None,
        description=(
            "The proxy password as a workspace secret (id from the secrets catalog). "
            "It is read when an instance starts; changing the secret's value takes "
            "effect at the instance's next start."
        ),
    )
    allow_plaintext_credentials: bool = Field(
        default=False,
        description="Send the credentials to an http or socks5 proxy, where they are unencrypted.",
    )

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name cannot be empty or whitespace")
        return v

    @field_validator("upstream_url")
    @classmethod
    def _upstream(cls, v: str) -> str:
        return validate_upstream_url(v)

    @model_validator(mode="after")
    def _credentials(self) -> EgressExitCreate:
        errors = credential_errors(
            upstream_url=self.upstream_url,
            username=self.username,
            password_secret_id=self.password_secret_id,
            allow_plaintext_credentials=self.allow_plaintext_credentials,
        )
        if errors:
            raise ValueError("; ".join(errors))
        return self


class EgressExitUpdate(BaseModel):
    """Patch an exit: only the fields sent change; null clears an optional one."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    upstream_url: str | None = Field(default=None, max_length=512)
    username: str | None = Field(default=None, max_length=MAX_CREDENTIAL_BYTES)
    password_secret_id: UUID | None = None
    allow_plaintext_credentials: bool | None = None

    @field_validator("upstream_url")
    @classmethod
    def _upstream(cls, v: str | None) -> str | None:
        return validate_upstream_url(v) if v is not None else None


def validate_spec_egress_exit(value: object) -> None:
    """An instance binds an exit by its id; anything else is refused before it is stored."""
    if value is None:
        return
    if not isinstance(value, str):
        raise ValueError("json_spec.egress_exit must be an egress exit id")
    try:
        UUID(value)
    except ValueError as e:
        raise ValueError("json_spec.egress_exit must be an egress exit id") from e
