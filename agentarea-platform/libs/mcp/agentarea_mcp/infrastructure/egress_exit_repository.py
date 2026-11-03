"""Egress exit persistence: a workspace's own exits, and nobody else's."""

from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from agentarea_secrets.models import SecretReference
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea_mcp.domain.egress_exit_model import EGRESS_EXIT_SPEC_KEY, EgressExit
from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance

REFERENCE_CONSUMER_TYPE = "egress_exit"


class EgressExitRepository(WorkspaceScopedRepository[EgressExit]):
    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, EgressExit, user_context)

    async def bound_instances(self, exit_id: UUID) -> list[MCPServerInstance]:
        """The workspace's MCP instances whose json_spec binds this exit."""
        result = await self.session.execute(
            select(MCPServerInstance).where(
                MCPServerInstance.workspace_id == self.user_context.workspace_id,
                MCPServerInstance.json_spec[EGRESS_EXIT_SPEC_KEY].as_string() == str(exit_id),
            )
        )
        return list(result.scalars().all())

    async def stage_password_reference(self, exit_id: UUID, secret_id: UUID | None) -> None:
        """Replace this exit's entry in the secret's reverse index; the next commit writes it."""
        await self.session.execute(
            delete(SecretReference).where(
                SecretReference.consumer_type == REFERENCE_CONSUMER_TYPE,
                SecretReference.consumer_id == str(exit_id),
                SecretReference.workspace_id == self.user_context.workspace_id,
            )
        )
        if secret_id is not None:
            self.session.add(
                SecretReference(
                    workspace_id=self.user_context.workspace_id,
                    secret_id=secret_id,
                    consumer_type=REFERENCE_CONSUMER_TYPE,
                    consumer_id=str(exit_id),
                    field="password",
                )
            )
