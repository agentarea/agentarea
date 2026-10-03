"""The A2A agent card, built once for every surface that serves it.

The public ``.well-known/agent-card.json`` and the authenticated
``GetExtendedAgentCard`` RPC both come from :func:`build_agent_card`, so the two
cannot advertise different endpoints, versions or security schemes. The card is
the SDK's ``a2a.types.AgentCard`` proto; :func:`agent_card_json` renders it in
the protocol's JSON form.
"""

from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentExtension,
    AgentInterface,
    AgentProvider,
    AgentSkill,
    HTTPAuthSecurityScheme,
    SecurityRequirement,
    SecurityScheme,
    StringList,
)
from a2a.utils.constants import PROTOCOL_VERSION_CURRENT, TransportProtocol
from agentarea_common.config import get_settings
from google.protobuf.json_format import MessageToDict
from google.protobuf.struct_pb2 import Struct

A2UI_EXTENSION_URI = "https://a2ui.org/a2a-extension/a2ui/v0.9"
A2UI_BASIC_CATALOG = "https://a2ui.org/specification/v0_9/basic_catalog.json"
BEARER_SCHEME = "bearer"
_MODES = ["text/plain", "application/json"]


def agent_rpc_url(agent_id: UUID) -> str:
    """The JSON-RPC endpoint of an agent under the API host."""
    return f"{get_settings().app.API_URL.rstrip('/')}/v1/agents/{agent_id}/a2a/rpc"


def agent_host_rpc_url(agent_id: UUID) -> str:
    """The JSON-RPC endpoint of an agent on its own host: the host's root."""
    return f"{get_settings().app.a2a_agent_url(agent_id)}/"


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def _skills(agent: Any, *, extended: bool) -> list[AgentSkill]:
    skills = [
        AgentSkill(
            id="text-processing",
            name="Text Processing",
            description=f"Process and respond to text messages using {agent.name}",
            tags=["text", "chat"],
            input_modes=["text/plain"],
            output_modes=["text/plain"],
        )
    ]
    if not extended:
        return skills
    if isinstance(agent.tools, list) and agent.tools:
        skills.append(
            AgentSkill(
                id="tool-execution",
                name="Tool Execution",
                description=f"Execute tools and integrations using {agent.name}",
                tags=["tools", "integration"],
                input_modes=["text/plain"],
                output_modes=_MODES,
            )
        )
    if agent.planning:
        skills.append(
            AgentSkill(
                id="task-planning",
                name="Task Planning",
                description=f"Break down complex tasks into steps using {agent.name}",
                tags=["planning"],
                input_modes=["text/plain"],
                output_modes=["text/plain"],
            )
        )
    return skills


def build_agent_card(agent: Any, *, rpc_url: str, extended: bool) -> AgentCard:
    """Build the card for ``agent``; ``extended`` adds the skills only members see.

    ``rpc_url`` is the endpoint on the origin the card was fetched from, so a
    client never follows a card to a host other than the one it was given.
    """
    capabilities = AgentCapabilities(
        streaming=True, push_notifications=True, extended_agent_card=True
    )
    if agent.a2ui_enabled:
        params = Struct()
        params.update({"supportedCatalogIds": [A2UI_BASIC_CATALOG]})
        capabilities.extensions.append(AgentExtension(uri=A2UI_EXTENSION_URI, params=params))

    return AgentCard(
        name=agent.name,
        description=agent.description or f"AI agent {agent.name}",
        supported_interfaces=[
            AgentInterface(
                url=rpc_url,
                protocol_binding=TransportProtocol.JSONRPC.value,
                protocol_version=PROTOCOL_VERSION_CURRENT,
            )
        ],
        provider=AgentProvider(organization="AgentArea", url=_origin(rpc_url)),
        version="1.0.0",
        capabilities=capabilities,
        security_schemes={
            BEARER_SCHEME: SecurityScheme(
                http_auth_security_scheme=HTTPAuthSecurityScheme(scheme="bearer")
            )
        },
        security_requirements=[SecurityRequirement(schemes={BEARER_SCHEME: StringList()})],
        default_input_modes=_MODES,
        default_output_modes=_MODES,
        skills=_skills(agent, extended=extended),
    )


def agent_card_json(card: AgentCard) -> dict[str, Any]:
    return MessageToDict(card)
