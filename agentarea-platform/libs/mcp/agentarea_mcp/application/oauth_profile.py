"""What a connection authorizes against, and where its OAuth client comes from.

Every connection kind that signs in with OAuth — a remote MCP server, a trusted
catalog API — reduces to one ``OAuthProfile``: the authorization server's
endpoints, the scopes, and the origins its tokens may reach. Which OAuth client
authorizes it is decided here, once, for all of them.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Literal

from agentarea_common.config import MCPOAuthApp

from agentarea_mcp.application.platform_oauth_app import platform_oauth_app, platform_oauth_apps

CredentialSource = Literal["platform", "dynamic"]


@dataclass(frozen=True)
class OAuthProfile:
    """One authorization server as a connection uses it.

    ``issuer`` is set when discovery found the server (remote MCP) and absent
    for a trusted catalog template, which names endpoints instead.
    ``resource_origins`` are where the minted tokens are sent.
    """

    provider: str
    authorization_endpoint: str
    token_endpoint: str
    resource_origins: tuple[str, ...]
    issuer: str | None = None
    registration_endpoint: str | None = None
    scopes: tuple[str, ...] = ()
    # RFC 8707 resource indicator; remote MCP servers only.
    resource: str = ""
    offline_access_supported: bool = False
    authorize_params: Mapping[str, str] = field(default_factory=dict)
    authorization_scheme: str = "Bearer"
    client_auth_method: str = "client_secret_post"

    def served_by(self, app: MCPOAuthApp) -> "OAuthProfile":
        """This profile with the platform app's endpoints, which alone receive its secret."""
        return replace(
            self,
            issuer=app.issuer,
            authorization_endpoint=app.authorization_endpoint,
            token_endpoint=app.token_endpoint,
        )


def platform_app_for(profile: OAuthProfile) -> MCPOAuthApp | None:
    """The operator's OAuth app that may authorize ``profile``, if any.

    A discovered server is matched on its issuer; a catalog template, which has
    none, on both endpoints, so the client secret only ever goes to a token
    endpoint the operator configured. Either way the app must serve every
    origin the profile sends tokens to.
    """
    if profile.issuer is not None:
        app = platform_oauth_app(profile.issuer)
    else:
        app = next(
            (
                candidate
                for candidate in platform_oauth_apps()
                if candidate.authorization_endpoint == profile.authorization_endpoint
                and candidate.token_endpoint == profile.token_endpoint
            ),
            None,
        )
    if app is None:
        return None
    if not set(profile.resource_origins) <= set(app.resource_origins):
        return None
    return app


def auto_credential_source(profile: OAuthProfile) -> CredentialSource | None:
    """The client an unattended Connect uses: platform app, then DCR, else none."""
    if platform_app_for(profile) is not None:
        return "platform"
    if profile.registration_endpoint:
        return "dynamic"
    return None
