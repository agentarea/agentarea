"""The A2A agent card, built once for every surface that serves it.

The public ``.well-known/agent-card.json`` and the authenticated
``GetExtendedAgentCard`` RPC both come from :func:`build_agent_card`, so the two
cannot advertise different endpoints, versions or security schemes. The card is
the SDK's ``a2a.types.AgentCard`` proto; :func:`agent_card_json` renders it in
the protocol's JSON form.
"""

from typing import Any
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
from fastapi import Request
from google.protobuf.json_format import MessageToDict
from google.protobuf.struct_pb2 import Struct

A2UI_EXTENSION_URI = "https://a2ui.org/a2a-extension/a2ui/v0.9"
A2UI_BASIC_CATALOG = "https://a2ui.org/specification/v0_9/basic_catalog.json"
BEARER_SCHEME = "bearer"
_MODES = ["text/plain", "application/json"]


def get_base_url(request: Request) -> str:
    return f"{request.url.scheme}://{request.url.netloc}"


def agent_rpc_url(base_url: str, agent_id: UUID) -> str:
    return f"{base_url}/v1/agents/{agent_id}/a2a/rpc"


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


def build_agent_card(agent: Any, *, base_url: str, agent_id: UUID, extended: bool) -> AgentCard:
    """Build the card for ``agent``; ``extended`` adds the skills only members see."""
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
                url=agent_rpc_url(base_url, agent_id),
                protocol_binding=TransportProtocol.JSONRPC.value,
                protocol_version=PROTOCOL_VERSION_CURRENT,
            )
        ],
        provider=AgentProvider(organization="AgentArea", url=base_url),
        version="1.0.0",
        documentation_url=f"{base_url}/v1/agents/{agent_id}/.well-known/a2a-info.json",
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
