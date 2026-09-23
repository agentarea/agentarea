"""Resolve principal ids into whoever they belong to.

`created_by` appears on 28 tables, and anything rendering one of those rows
eventually wants a name beside the id. Attaching that name to each read model
would mean repeating the same identity lookup per resource, and would couple
every one of them to the identity provider's availability. It lives here
instead: one resource, joined by the caller, cacheable on its own terms —
names change about as often as people are hired, while the rows referencing
them change constantly.

`type` is part of the answer because an id is not necessarily a person. Users,
agents and the reserved platform principals resolve today; clients are expected
(see #425, principal typing), and callers that switch on `type` keep working
when they arrive.

Agents resolve before users, and out of our own database. Beyond being cheaper,
it means an id belonging to an agent is never asked about in the identity
provider at all, and the order settles which answer wins if an agent id ever
collides with an identity id.

Ids nothing can resolve are left out of the response entirely rather than
echoed back with the id standing in for a name — the caller renders an unknown
principal instead of being handed a guess.
"""

from enum import StrEnum

from agentarea_api.api.deps.services import ReadAgentServiceDep
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.auth.identity_directory import get_identity_directory, identity_for
from agentarea_common.auth.route_authz import unrestricted
from agentarea_common.constants import PLATFORM_PRINCIPAL_ID
from fastapi import APIRouter, Query
from pydantic import BaseModel

router = APIRouter(prefix="/principals", tags=["principals"])

# `system` is the tasks table's column default, `platform` the constant used by
# platform-internal contexts. Neither is a person and neither has an entry in
# the identity provider, so asking it about them would only waste a round trip.
RESERVED_PRINCIPAL_IDS = frozenset({PLATFORM_PRINCIPAL_ID, "system"})

# Ids are capped so one request cannot fan out into an unbounded number of
# lookups against the identity provider.
MAX_IDS = 200


class PrincipalType(StrEnum):
    """What kind of thing an id refers to."""

    USER = "user"
    AGENT = "agent"
    PLATFORM = "platform"


class PrincipalResponse(BaseModel):
    id: str
    type: PrincipalType
    # Null whenever the authority for it has nothing to offer — a reserved
    # principal has no name, and an unnamed identity is not given one.
    display_name: str | None = None
    email: str | None = None


# Registered on the bare prefix, not "/": this is read with a query string on
# every call, and a 307 to add a trailing slash would double every request.
@router.get(
    "",
    response_model=list[PrincipalResponse],
    dependencies=[
        unrestricted("resolves ids the caller already holds into display names, nothing more")
    ],
)
async def resolve_principals(
    user_context: UserContextDep,
    agent_service: ReadAgentServiceDep,
    ids: list[str] = Query(default_factory=list, description="Principal ids to resolve"),
) -> list[PrincipalResponse]:
    """Resolve the given ids. Unresolvable ids are absent from the response."""
    unique_ids = list(dict.fromkeys(principal_id for principal_id in ids if principal_id))[:MAX_IDS]

    candidates = [pid for pid in unique_ids if pid not in RESERVED_PRINCIPAL_IDS]

    # Listed rather than fetched by id: the service has no bulk get, and this is
    # the same workspace-scoped listing GET /v1/tasks already does per request to
    # fill in agent_name. Being workspace-scoped is also what keeps another
    # workspace's agent from resolving here.
    agent_names: dict[str, str] = {}
    if candidates:
        agent_names = {str(agent.id): agent.name for agent in await agent_service.list()}

    directory_lookups = [pid for pid in candidates if pid not in agent_names]

    identities = {}
    directory = get_identity_directory()
    if directory is not None:
        identities = await directory.resolve(directory_lookups)

    resolved: list[PrincipalResponse] = []
    for principal_id in unique_ids:
        if principal_id in RESERVED_PRINCIPAL_IDS:
            resolved.append(PrincipalResponse(id=principal_id, type=PrincipalType.PLATFORM))
            continue

        agent_name = agent_names.get(principal_id)
        if agent_name is not None:
            resolved.append(
                PrincipalResponse(
                    id=principal_id,
                    type=PrincipalType.AGENT,
                    display_name=agent_name,
                )
            )
            continue

        identity = identity_for(
            principal_id,
            identities,
            current_user_id=user_context.user_id,
            current_user_email=user_context.email,
        )
        if identity.display_name is None and identity.email is None:
            continue
        resolved.append(
            PrincipalResponse(
                id=principal_id,
                type=PrincipalType.USER,
                display_name=identity.display_name,
                email=identity.email,
            )
        )

    return resolved
