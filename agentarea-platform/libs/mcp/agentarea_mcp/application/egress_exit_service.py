"""Egress exits: define the workspace's own, list them with the platform's, bind one to an instance."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from agentarea_common.audit import audited
from agentarea_common.auth.permission import require_permission
from agentarea_common.infrastructure.secret_manager import BaseSecretManager
from agentarea_common.utils.url_safety import OutboundPolicy, UnsafeUrlError, validate_outbound_url
from agentarea_secrets.catalog_service import SecretCatalogService

from agentarea_mcp.domain.egress_exit_model import EgressExit
from agentarea_mcp.domain.transport import CONTAINER_TRANSPORTS
from agentarea_mcp.infrastructure.egress_exit_repository import EgressExitRepository
from agentarea_mcp.package_import import retire_runtime_before_mutation
from agentarea_mcp.schemas.egress_exit_dto import (
    EgressExitCreate,
    EgressExitUpdate,
    credential_errors,
)

if TYPE_CHECKING:
    from agentarea_common.base.repository_factory import RepositoryFactory

logger = logging.getLogger(__name__)

UPSTREAM_NOT_ALLOWED = "upstream_url must be a public address this deployment may reach"
# Fields the proxy is handed when an instance starts: changing one retires every
# running instance bound to the exit, so its next start carries the new route.
ROUTE_FIELDS = frozenset(
    {"upstream_url", "username", "password_secret_id", "allow_plaintext_credentials"}
)


class EgressExitNotFoundError(LookupError):
    def __init__(self, exit_id: UUID | str):
        self.exit_id = exit_id
        super().__init__(f"Egress exit {exit_id} not found")


class EgressExitValidationError(ValueError):
    """An exit that cannot be saved or bound as given."""


class EgressExitInUseError(RuntimeError):
    """MCP instances leave through this exit, so it cannot be deleted under them."""


class PlatformEgressExitError(PermissionError):
    """A platform exit is the deployment's; a tenant may bind it but not change it."""


async def _assert_upstream_public(upstream_url: str) -> None:
    """Refuse, when it is saved, a proxy address the egress proxy would refuse to dial."""
    parts = urlsplit(upstream_url)
    try:
        await asyncio.to_thread(
            validate_outbound_url,
            f"http://{parts.netloc}",
            policy=OutboundPolicy.from_env(),
        )
    except UnsafeUrlError as e:
        logger.info("Refused egress exit upstream_url on save: %s", e)
        raise EgressExitValidationError(UPSTREAM_NOT_ALLOWED) from e


class EgressExitService:
    def __init__(self, repository_factory: RepositoryFactory, secret_manager: BaseSecretManager):
        self.repository_factory = repository_factory
        self.repository = repository_factory.create_repository(EgressExitRepository)
        self.user_context = repository_factory.user_context
        self.catalog = SecretCatalogService(
            session=self.repository.session,
            user_context=self.user_context,
            secret_manager=secret_manager,
        )

    async def list(self) -> list[EgressExit]:
        """The workspace's own exits and the platform's, newest first."""
        return await self.repository.list_all()

    async def get(self, exit_id: UUID) -> EgressExit:
        exit_ = await self.repository.get_by_id(exit_id)
        if exit_ is None:
            raise EgressExitNotFoundError(exit_id)
        return exit_

    async def require_bindable(self, exit_id: UUID | str) -> EgressExit:
        """The exit an instance of this workspace asks to leave through, if the caller may use it."""
        exit_ = await self.repository.get_by_id(exit_id)
        if exit_ is None:
            raise EgressExitNotFoundError(exit_id)
        if not exit_.is_platform:
            await require_permission("use", "egress_exit", str(exit_.id), self.user_context)
        return exit_

    @audited("egress_exit.create", resource_type="egress_exit")
    async def create(self, payload: EgressExitCreate) -> EgressExit:
        await _assert_upstream_public(payload.upstream_url)
        if payload.password_secret_id is not None:
            await self.catalog.get_for_use(payload.password_secret_id)
        exit_id = uuid4()
        # Staged before the insert, which commits it with the row.
        await self.repository.stage_password_reference(exit_id, payload.password_secret_id)
        return await self.repository.create(
            id=exit_id,
            name=payload.name,
            description=payload.description,
            upstream_url=payload.upstream_url,
            username=payload.username,
            password_secret_id=payload.password_secret_id,
            allow_plaintext_credentials=payload.allow_plaintext_credentials,
        )

    @audited("egress_exit.update", resource_type="egress_exit", resource_id_param="exit_id")
    async def update(self, exit_id: UUID, payload: EgressExitUpdate) -> EgressExit:
        current = await self._require_own(exit_id)
        changes: dict[str, Any] = payload.model_dump(exclude_unset=True)
        for required in ("name", "upstream_url", "allow_plaintext_credentials"):
            if required in changes and changes[required] is None:
                raise EgressExitValidationError(f"{required} cannot be cleared")
        changes = {k: v for k, v in changes.items() if getattr(current, k) != v}
        if not changes:
            return current

        merged = {field: changes.get(field, getattr(current, field)) for field in ROUTE_FIELDS}
        errors = credential_errors(**merged)
        if errors:
            raise EgressExitValidationError("; ".join(errors))
        if "upstream_url" in changes:
            await _assert_upstream_public(changes["upstream_url"])
        if changes.get("password_secret_id") is not None:
            await self.catalog.get_for_use(changes["password_secret_id"])

        if ROUTE_FIELDS.intersection(changes):
            # A running instance holds the route it started with; retire it before
            # the change is stored, so a failure leaves the old route honest.
            for instance in await self.repository.bound_instances(exit_id):
                if instance.transport in CONTAINER_TRANSPORTS:
                    await retire_runtime_before_mutation(instance.id)

        if "password_secret_id" in changes:
            await self.repository.stage_password_reference(exit_id, changes["password_secret_id"])
        updated = await self.repository.update(exit_id, **changes)
        if updated is None:
            raise EgressExitNotFoundError(exit_id)
        return updated

    @audited("egress_exit.delete", resource_type="egress_exit", resource_id_param="exit_id")
    async def delete(self, exit_id: UUID) -> None:
        await self._require_own(exit_id)
        bound = await self.repository.bound_instances(exit_id)
        if bound:
            names = ", ".join(sorted(instance.name for instance in bound))
            raise EgressExitInUseError(
                f"{len(bound)} MCP instance(s) leave through this exit ({names}); "
                "unbind them before deleting it"
            )
        await self.repository.stage_password_reference(exit_id, None)
        if not await self.repository.delete(exit_id):
            raise EgressExitNotFoundError(exit_id)

    async def _require_own(self, exit_id: UUID) -> EgressExit:
        exit_ = await self.get(exit_id)
        if exit_.is_platform:
            raise PlatformEgressExitError(
                f"Egress exit {exit_id} is the platform's; it can be bound but not changed"
            )
        return exit_
