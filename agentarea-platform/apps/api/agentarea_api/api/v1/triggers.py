"""Trigger management API endpoints for AgentArea.

This module implements REST endpoints for trigger CRUD operations, lifecycle management,
and execution history monitoring. It follows the existing API patterns for authentication,
validation, error handling, and response formatting.

Key endpoints:
- POST /triggers - Create a new trigger
- GET /triggers - List triggers with filtering
- GET /triggers/{trigger_id} - Get a specific trigger
- PUT /triggers/{trigger_id} - Update a trigger
- DELETE /triggers/{trigger_id} - Delete a trigger
- POST /triggers/{trigger_id}/enable - Enable a trigger
- POST /triggers/{trigger_id}/disable - Disable a trigger
- GET /triggers/{trigger_id}/executions - Get execution history
- GET /triggers/{trigger_id}/status - Get trigger status and schedule info
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal, cast
from uuid import UUID

from agentarea_api.api.deps.services import (
    BaseSecretManagerDep,
    SecretCatalogServiceDep,
    get_trigger_health_check,
    get_trigger_service,
)
from agentarea_api.api.v1._icons import CHANNEL_ICON_NAMESPACE, build_icon_url
from agentarea_common.auth.dependencies import UserContext, get_user_context
from agentarea_common.auth.route_authz import requires, unrestricted
from agentarea_common.config.app import get_app_settings
from agentarea_common.config.database import get_db_session
from agentarea_common.infrastructure.secret_manager import BaseSecretManager
from agentarea_common.utils.types import UtcDatetime
from agentarea_secrets.catalog_service import (
    ManagedSecretError,
    SecretAccessDeniedError,
    SecretCatalogService,
    SecretNotFoundError,
)
from agentarea_tasks.infrastructure.orm import TaskORM
from agentarea_triggers.channels.webhook_service import ChannelWebhookService
from agentarea_triggers.domain.channel_events import CHANNEL_EVENTS, get_trigger_catalog
from agentarea_triggers.infrastructure.orm import TriggerExecutionORM
from agentarea_triggers.schemas.dto import TriggerCreate, TriggerUpdate
from agentarea_triggers.trigger_service import (
    TriggerNotFoundError,
    TriggerService,
    TriggerValidationError,
)
from agentarea_triggers.webhook_verification import (
    channel_credential_secret_name,
    redact_secret_fields,
)
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import Numeric, and_, func, select
from sqlalchemy import cast as sa_cast
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/triggers", tags=["triggers"])


# API Response Models


class TriggerResponse(BaseModel):
    """Response model for trigger data."""

    id: UUID
    name: str
    description: str
    agent_id: UUID
    trigger_type: str
    is_active: bool
    task_parameters: dict[str, Any]
    conditions: dict[str, Any]
    created_at: UtcDatetime
    updated_at: UtcDatetime
    created_by: str

    # Business logic safety
    failure_threshold: int
    consecutive_failures: int
    last_execution_at: UtcDatetime | None = None

    # Type-specific fields (optional)
    cron_expression: str | None = None
    timezone: str | None = None
    next_run_time: UtcDatetime | None = None
    webhook_id: str | None = None
    allowed_methods: list[str] | None = None
    webhook_type: str | None = None
    validation_rules: dict[str, Any] | None = None
    webhook_config: dict[str, Any] | None = None
    event_types: list[str] = Field(default_factory=list)

    # Poll-based extractor type (e.g., "imap")
    data_extractor: str | None = None

    # Channel credentials indicator (actual credentials never returned)
    has_channel_credentials: bool = False

    @classmethod
    def from_domain_model(
        cls, trigger: Any, has_channel_credentials: bool = False
    ) -> "TriggerResponse":
        """Create response from domain model."""
        # Base fields
        response_data = {
            "id": trigger.id,
            "name": trigger.name,
            "description": trigger.description,
            "agent_id": trigger.agent_id,
            "trigger_type": trigger.trigger_type.value
            if hasattr(trigger.trigger_type, "value")
            else str(trigger.trigger_type),
            "is_active": trigger.is_active,
            "task_parameters": trigger.task_parameters,
            "conditions": trigger.conditions,
            "created_at": trigger.created_at,
            "updated_at": trigger.updated_at,
            "created_by": trigger.created_by,
            "failure_threshold": trigger.failure_threshold,
            "consecutive_failures": trigger.consecutive_failures,
            "last_execution_at": trigger.last_execution_at,
        }

        # Add type-specific fields
        if hasattr(trigger, "cron_expression"):
            response_data.update(
                {
                    "cron_expression": trigger.cron_expression,
                    "timezone": trigger.timezone,
                    "next_run_time": getattr(trigger, "next_run_time", None),
                    "data_extractor": getattr(trigger, "data_extractor", None),
                }
            )

        if hasattr(trigger, "webhook_id"):
            response_data.update(
                {
                    "webhook_id": trigger.webhook_id,
                    "allowed_methods": trigger.allowed_methods,
                    "webhook_type": trigger.webhook_type.value
                    if hasattr(trigger.webhook_type, "value")
                    else str(trigger.webhook_type),
                    "validation_rules": redact_secret_fields(trigger.validation_rules),
                    "webhook_config": redact_secret_fields(trigger.webhook_config),
                    "event_types": getattr(trigger, "event_types", []) or [],
                }
            )

        response_data["has_channel_credentials"] = has_channel_credentials

        return cls(**response_data)


class TriggerExecutionResponse(BaseModel):
    """Response model for trigger execution data."""

    id: UUID
    trigger_id: UUID
    executed_at: UtcDatetime
    status: str
    task_id: UUID | None = None
    execution_time_ms: int
    error_message: str | None = None
    trigger_data: dict[str, Any]
    workflow_id: str | None = None
    run_id: str | None = None
    fired_by: str | None = Field(
        default=None,
        description=(
            "Principal who asked for this run, when a person did. Null means the "
            "trigger fired itself. Resolve the name through GET /v1/principals."
        ),
    )
    cost_usd: float | None = Field(
        default=None,
        description=(
            "What the task this run created has spent so far. Null when the run "
            "created no task, or the task has not reported a cost yet."
        ),
    )

    @classmethod
    def from_domain_model(cls, execution: Any) -> "TriggerExecutionResponse":
        """Create response from domain model."""
        return cls(
            id=execution.id,
            trigger_id=execution.trigger_id,
            executed_at=execution.executed_at,
            status=execution.status.value
            if hasattr(execution.status, "value")
            else str(execution.status),
            task_id=execution.task_id,
            execution_time_ms=execution.execution_time_ms,
            error_message=execution.error_message,
            trigger_data=execution.trigger_data,
            workflow_id=execution.workflow_id,
            run_id=execution.run_id,
            fired_by=execution.fired_by,
        )


class TriggerStatusResponse(BaseModel):
    """Response model for trigger status information."""

    trigger_id: UUID
    is_active: bool
    last_execution_at: UtcDatetime | None = None
    consecutive_failures: int
    should_disable_due_to_failures: bool

    # Schedule information for cron triggers
    schedule_info: dict[str, Any] | None = None


class ExecutionHistoryResponse(BaseModel):
    """Response model for paginated execution history."""

    executions: list[TriggerExecutionResponse]
    total: int
    page: int
    page_size: int
    has_next: bool


class ExecutionMetricsResponse(BaseModel):
    """Response model for execution metrics."""

    trigger_id: UUID
    period_hours: int | None = Field(
        default=None, description="Window these metrics cover. Null means the whole history."
    )
    total_executions: int
    successful_executions: int
    failed_executions: int
    timeout_executions: int
    success_rate: float = Field(description="Percentage, 0-100.")
    failure_rate: float = Field(description="Percentage, 0-100.")
    avg_execution_time_ms: float
    min_execution_time_ms: int
    max_execution_time_ms: int
    total_cost_usd: float = Field(default=0.0, description="Spend of the tasks these runs created.")
    avg_cost_usd: float = Field(
        default=0.0, description="Spend per run that produced a costed task."
    )
    costed_executions: int = Field(
        default=0, description="Runs whose task reported a cost; the divisor behind avg_cost_usd."
    )


class ExecutionTimelineResponse(BaseModel):
    """Response model for execution timeline."""

    trigger_id: UUID
    period_hours: int
    timeline: list[dict[str, Any]]


class ExecutionCorrelationResponse(BaseModel):
    """Response model for execution correlation data."""

    executions: list[dict[str, Any]]
    total: int
    page: int
    page_size: int
    has_next: bool


class TriggerExecuteRequest(BaseModel):
    """Request model for executing a trigger via the event service."""

    events: list[dict[str, Any]] = Field(default_factory=list)
    channel_origin: dict[str, Any] = Field(default_factory=dict)


class TriggerRunResponse(BaseModel):
    """Result of firing a trigger once by hand."""

    status: Literal["started", "skipped"] = Field(
        description=(
            "'started' when a task was created and is now running. 'skipped' when "
            "the trigger's own conditions rejected the run -- a real answer about "
            "the trigger, not an error."
        )
    )
    trigger_id: UUID
    execution_id: UUID
    task_id: UUID | None = Field(
        default=None, description="The task to watch. Absent when the run was skipped."
    )
    reason: str | None = Field(default=None, description="Why the run was skipped, when it was.")


# Utility Functions


DatabaseSessionDep = Annotated[AsyncSession, Depends(get_db_session)]


def _task_cost_expr():
    """Spend of a task, matching the task repository's own accounting.

    ``own_cost`` excludes what delegated children spent — those are billed on
    their own rows — and ``total_cost`` is the fallback for results written
    before the two were split.
    """
    return func.coalesce(
        sa_cast(TaskORM.result.op("->>")("own_cost"), Numeric),
        sa_cast(TaskORM.result.op("->>")("total_cost"), Numeric),
        0,
    )


async def _costs_by_task(
    session: AsyncSession, workspace_id: str, task_ids: list[UUID]
) -> dict[UUID, float]:
    """Spend per task id, for the tasks a page of runs created."""
    if not task_ids:
        return {}
    stmt = select(TaskORM.id, _task_cost_expr().label("cost")).where(
        and_(TaskORM.workspace_id == workspace_id, TaskORM.id.in_(task_ids))
    )
    rows = (await session.execute(stmt)).all()
    return {row.id: float(row.cost or 0) for row in rows}


async def _trigger_spend(
    session: AsyncSession, workspace_id: str, trigger_id: UUID, hours: int | None
) -> tuple[float, int]:
    """Total spend of one trigger and how many of its runs produced a task.

    The cost of a run is not on the run: the execution row is written the
    moment the task is handed off, while the bill accrues over the task's life.
    So spend is always a join away, never a stored column.
    """
    conditions = [
        TriggerExecutionORM.trigger_id == trigger_id,
        TriggerExecutionORM.workspace_id == workspace_id,
        TaskORM.workspace_id == workspace_id,
    ]
    if hours is not None:
        conditions.append(
            TriggerExecutionORM.executed_at >= datetime.utcnow() - timedelta(hours=hours)
        )

    stmt = (
        select(
            func.coalesce(func.sum(_task_cost_expr()), 0).label("total"),
            func.count(TaskORM.id).label("costed"),
        )
        .select_from(TriggerExecutionORM)
        .join(TaskORM, TaskORM.id == TriggerExecutionORM.task_id)
        .where(and_(*conditions))
    )
    row = (await session.execute(stmt)).one()
    return float(row.total or 0), int(row.costed or 0)


async def _has_credentials(secret_manager: Any, trigger: Any, trigger_id: UUID) -> bool:
    """Check if channel credentials exist for a trigger.

    Presence only — the value is never read, so a credential this deployment can
    no longer decrypt still reports as configured. And because this is one
    display flag on the response, a store that cannot answer at all costs the
    flag, not the trigger: reading a trigger used to fail outright whenever its
    credential had become unreadable.
    """
    channel_type = "generic"
    if hasattr(trigger, "webhook_type"):
        wt = trigger.webhook_type
        channel_type = wt.value if hasattr(wt, "value") else str(wt)
    secret_name = channel_credential_secret_name(channel_type, trigger_id)
    try:
        return await secret_manager.has_secret(secret_name)
    except Exception as e:
        logger.warning(
            f"Could not resolve channel credentials for trigger {trigger_id}: {e}", exc_info=True
        )
        return False


# API Endpoints


@router.get(
    "/catalog",
    dependencies=[unrestricted("platform catalogue data, identical for every workspace")],
)
async def get_catalog(
    user_context: UserContext = Depends(get_user_context),
) -> list[dict[str, Any]]:
    """Get the trigger catalog — available trigger types with metadata and events.

    ``icon`` is stored as data (an asset id or a full URL); it is resolved here
    into ``icon_url`` so the frontend renders whatever it is handed and never
    carries a table of which channels exist.
    """
    return [
        {**entry, "icon_url": build_icon_url(CHANNEL_ICON_NAMESPACE, entry.get("icon"))}
        for entry in get_trigger_catalog()
    ]


@router.get(
    "/channels/events",
    dependencies=[unrestricted("platform catalogue data, identical for every workspace")],
)
async def get_channel_events(
    user_context: UserContext = Depends(get_user_context),
) -> dict[str, list[str]]:
    """Get supported event types for all channels.
    Returns a mapping of channel type to list of event types.
    """
    return CHANNEL_EVENTS


def get_channel_webhook_service() -> ChannelWebhookService:
    """Composition root for inbound webhook registration.

    Reads the reachable ingress base (TELEGRAM_WEBHOOK_BASE_URL if set, else
    API_BASE_URL) and hands the endpoints a service that knows nothing about any
    specific channel — that lives behind the WebhookRegistrar registry.
    """
    settings = get_app_settings()
    base = getattr(settings, "TELEGRAM_WEBHOOK_BASE_URL", "") or settings.API_BASE_URL
    return ChannelWebhookService(base)


def _channel_secret_name(trigger: Any, trigger_id: Any) -> str | None:
    """Secret name holding this trigger's channel credentials, if it is a webhook
    trigger. Only the naming convention lives here — no channel logic.
    """
    wt = getattr(trigger, "webhook_type", None)
    name = getattr(wt, "value", None) or str(wt or "")
    return channel_credential_secret_name(name, trigger_id) if name else None


async def _resolve_channel_credentials(
    credentials: dict[str, Any] | None,
    secret_catalog: SecretCatalogService,
    secret_manager: BaseSecretManager,
) -> dict[str, Any] | None:
    """Resolve workspace secret selections before persisting any trigger changes."""
    if not credentials:
        return credentials

    resolved = {}
    for field, credential in credentials.items():
        if not isinstance(credential, dict):
            # Existing clients provide credential values directly.
            resolved[field] = credential
            continue

        if set(credential) != {"secret_id"} or not isinstance(credential["secret_id"], str):
            raise HTTPException(
                status_code=422, detail="Invalid channel credential secret reference."
            )
        try:
            secret_id = UUID(credential["secret_id"])
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail="Invalid channel credential secret reference."
            ) from exc

        try:
            secret = await secret_catalog.get_for_use(secret_id)
        except SecretNotFoundError as exc:
            raise HTTPException(
                status_code=422,
                detail="Selected channel credential secret is not available in this workspace.",
            ) from exc
        except ManagedSecretError as exc:
            raise HTTPException(
                status_code=422,
                detail="Selected channel credential must be a user-owned workspace secret.",
            ) from exc
        except SecretAccessDeniedError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        try:
            value = await secret_manager.get_secret(secret.secret_name)
        except Exception:
            # Provider exceptions may include sensitive material; never forward or log them.
            raise HTTPException(
                status_code=422, detail="Selected channel credential secret could not be read."
            ) from None
        if not value:
            raise HTTPException(
                status_code=422, detail="Selected channel credential secret has no value."
            )
        resolved[field] = value

    return resolved


@router.post(
    "/",
    response_model=TriggerResponse,
    status_code=201,
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def create_trigger(
    secret_manager: BaseSecretManagerDep,
    secret_catalog: SecretCatalogServiceDep,
    payload: TriggerCreate = Body(...),
    user_context: UserContext = Depends(get_user_context),
    trigger_service: TriggerService = Depends(get_trigger_service),
    webhook_service: ChannelWebhookService = Depends(get_channel_webhook_service),
) -> TriggerResponse:
    """Create a new trigger.

    Creates a new trigger with the specified configuration. The trigger will be
    validated and, if it's a cron trigger, automatically scheduled.

    If channel_credentials are provided, they are stored encrypted in the secret
    store under key ``channel_cred:{webhook_type}:{trigger_id}``.

    Args:
        payload: Trigger creation DTO (single source of truth shared with MCP toolset).
        user_context: Authentication context.
        trigger_service: Injected trigger service.
        secret_manager: Injected secret manager for credential storage.
        secret_catalog: Workspace-scoped catalog for selected credential references.
        webhook_service: Injected service that registers the channel webhook.

    Returns:
        The created trigger.

    Raises:
        HTTPException: If validation fails or creation errors occur.
    """
    try:
        if not user_context.user_id:
            raise HTTPException(status_code=400, detail="User ID is required to create a trigger")

        credentials = await _resolve_channel_credentials(
            payload.channel_credentials, secret_catalog, secret_manager
        )

        # Convert DTO -> domain create. Done up-front so we can fold polling
        # channel credentials into ``data_extractor_config`` before persisting.
        trigger_data = payload.to_domain(
            created_by=user_context.user_id,
            workspace_id=user_context.workspace_id,
        )

        # For polling extractors, merge credentials into extractor config
        # so the Go polling service can read them (e.g. bot_token for Telegram).
        # Extractors that read the secret store themselves are excluded: that
        # column is plain JSON, and a mailbox password does not belong in it.
        from agentarea_triggers.extractors import resolves_own_credentials

        if (
            trigger_data.data_extractor
            and credentials
            and not resolves_own_credentials(trigger_data.data_extractor)
        ):
            trigger_data.data_extractor_config = {
                **(trigger_data.data_extractor_config or {}),
                **credentials,
            }

        # Create trigger
        trigger = await trigger_service.create_trigger(trigger_data)

        # Also store credentials encrypted in secret store for Python outbound delivery
        has_creds = False
        if credentials and secret_manager:
            # Channel type for secret key: use webhook_type or derive from data_extractor.
            # Extractor names like "telegram_polling" map to channel type via suffix stripping.
            extractor = payload.data_extractor or ""
            channel_type = payload.webhook_type or extractor.removesuffix("_polling") or "generic"
            secret_name = channel_credential_secret_name(channel_type, trigger.id)
            await secret_manager.set_secret(secret_name, json.dumps(credentials))
            has_creds = True
            logger.info(f"Stored channel credentials for trigger {trigger.id}")

        if has_creds:
            await webhook_service.register(
                channel_type=getattr(trigger, "webhook_type", None),
                webhook_id=getattr(trigger, "webhook_id", None),
                credentials=credentials,
            )

        logger.info(f"Created trigger {trigger.id} for agent {trigger.agent_id}")

        return TriggerResponse.from_domain_model(trigger, has_channel_credentials=has_creds)

    except HTTPException:
        raise
    except TriggerValidationError as e:
        logger.warning(f"Trigger validation failed: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception(f"Failed to create trigger: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.get(
    "/",
    response_model=list[TriggerResponse],
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def list_triggers(
    secret_manager: BaseSecretManagerDep,
    agent_id: UUID | None = Query(None, description="Filter by agent ID"),
    trigger_type: str | None = Query(None, description="Filter by trigger type (cron, webhook)"),
    active_only: bool = Query(False, description="Only return active triggers"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of triggers to return"),
    user_context: UserContext = Depends(get_user_context),
    trigger_service: TriggerService = Depends(get_trigger_service),
) -> list[TriggerResponse]:
    """List triggers with optional filtering.

    Returns a list of triggers that match the specified criteria. Supports
    filtering by agent ID, trigger type, and active status.

    Access Control:
        Returns all triggers within the current user's workspace (workspace isolation).
        All users in the same workspace can see all workspace triggers.

    Args:
        secret_manager: Injected secret manager (to resolve credential presence)
        agent_id: Optional agent ID filter
        trigger_type: Optional trigger type filter
        active_only: Whether to only return active triggers
        limit: Maximum number of triggers to return
        user_context: Authentication context
        trigger_service: Injected trigger service

    Returns:
        List of triggers matching the criteria
    """
    try:
        # Convert string trigger type to domain enum if provided
        domain_trigger_type = None
        if trigger_type:
            from agentarea_triggers.domain.enums import TriggerType

            if trigger_type.lower() == "cron":
                domain_trigger_type = TriggerType.CRON
            elif trigger_type.lower() == "webhook":
                domain_trigger_type = TriggerType.WEBHOOK
            else:
                raise HTTPException(status_code=400, detail=f"Invalid trigger type: {trigger_type}")

        # List triggers
        triggers = await trigger_service.list_triggers(
            agent_id=agent_id,
            trigger_type=domain_trigger_type,
            active_only=active_only,
            creator_scoped=False,
            limit=limit,
        )

        logger.info(f"Listed {len(triggers)} triggers")

        # Resolve credential presence per trigger concurrently so the flag is
        # correct on the list path too (not just create/update).
        creds_flags = await asyncio.gather(
            *(_has_credentials(secret_manager, trigger, trigger.id) for trigger in triggers)
        )
        return [
            TriggerResponse.from_domain_model(trigger, has_channel_credentials=has_creds)
            for trigger, has_creds in zip(triggers, creds_flags, strict=True)
        ]

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to list triggers: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


# Health check endpoint
@router.get(
    "/health",
    response_model=dict[str, Any],
    dependencies=[unrestricted("liveness probe, returns no workspace data")],
)
async def triggers_health_check(
    health_checker=Depends(get_trigger_health_check),
) -> dict[str, Any]:
    """Comprehensive health check endpoint for trigger system.

    Checks all trigger system components including:
    - Database connectivity
    - Temporal schedule manager
    - Webhook manager
    - Execution metrics

    Returns:
        Dictionary with detailed health status information
    """
    try:
        # Run comprehensive health check
        health_status = await health_checker.check_all_components()
        health_status["service"] = "triggers"

        return health_status

    except Exception:
        logger.error("Triggers health check failed", exc_info=True)
        return {
            "overall_status": "unhealthy",
            "service": "triggers",
            "error": "health check failed",
            "timestamp": datetime.utcnow().isoformat(),
            "components": {},
        }


@router.get(
    "/{trigger_id}",
    response_model=TriggerResponse,
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def get_trigger(
    trigger_id: UUID,
    secret_manager: BaseSecretManagerDep,
    user_context: UserContext = Depends(get_user_context),
    trigger_service: TriggerService = Depends(get_trigger_service),
) -> TriggerResponse:
    """Get a specific trigger by ID.

    Args:
        trigger_id: The unique identifier of the trigger
        secret_manager: Injected secret manager (to resolve credential presence)
        user_context: Authentication context
        trigger_service: Injected trigger service

    Returns:
        The trigger data

    Raises:
        HTTPException: If trigger not found
    """
    try:
        trigger = await trigger_service.get_trigger(trigger_id)

        if not trigger:
            raise HTTPException(status_code=404, detail=f"Trigger {trigger_id} not found")

        has_creds = await _has_credentials(secret_manager, trigger, trigger_id)
        return TriggerResponse.from_domain_model(trigger, has_channel_credentials=has_creds)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get trigger {trigger_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.put(
    "/{trigger_id}",
    response_model=TriggerResponse,
    dependencies=[requires("edit", "trigger", id_param="trigger_id")],
)
async def update_trigger(
    trigger_id: UUID,
    secret_manager: BaseSecretManagerDep,
    secret_catalog: SecretCatalogServiceDep,
    payload: TriggerUpdate = Body(...),
    user_context: UserContext = Depends(get_user_context),
    trigger_service: TriggerService = Depends(get_trigger_service),
    webhook_service: ChannelWebhookService = Depends(get_channel_webhook_service),
) -> TriggerResponse:
    """Update an existing trigger.

    Updates the specified trigger with the provided data. Only non-null fields
    in the request will be updated. Secret selections preserve unselected
    credential fields; legacy raw credentials replace the stored bundle.

    Args:
        trigger_id: The unique identifier of the trigger.
        payload: Trigger update DTO (single source of truth shared with MCP toolset).
        user_context: Authentication context.
        trigger_service: Injected trigger service.
        secret_manager: Injected secret manager for credential storage.
        secret_catalog: Workspace-scoped catalog for selected credential references.
        webhook_service: Injected service that registers the channel webhook.

    Returns:
        The updated trigger.

    Raises:
        HTTPException: If trigger not found or validation fails.
    """
    try:
        credentials = await _resolve_channel_credentials(
            payload.channel_credentials, secret_catalog, secret_manager
        )
        if credentials and any(
            isinstance(value, dict) for value in (payload.channel_credentials or {}).values()
        ):
            current_trigger = await trigger_service.get_trigger(trigger_id)
            if current_trigger is None:
                raise HTTPException(status_code=404, detail=f"Trigger {trigger_id} not found")
            secret_name = _channel_secret_name(current_trigger, trigger_id)
            if secret_name is None:
                extractor = getattr(current_trigger, "data_extractor", None) or ""
                channel_type = extractor.removesuffix("_polling") or "generic"
                secret_name = channel_credential_secret_name(channel_type, trigger_id)
            try:
                stored = await secret_manager.get_secret(secret_name)
                existing_credentials = json.loads(stored) if stored is not None else {}
                if not isinstance(existing_credentials, dict):
                    raise ValueError("Stored channel credentials must be an object")
            except Exception:
                raise HTTPException(
                    status_code=422,
                    detail="Existing channel credentials could not be read. No changes were saved.",
                ) from None
            credentials = {**existing_credentials, **credentials}
        trigger_update = payload.to_domain()

        # Update trigger
        updated_trigger = await trigger_service.update_trigger(trigger_id, trigger_update)

        # Update channel credentials if provided
        has_creds = False
        if credentials and secret_manager:
            # Determine channel type from the updated trigger
            channel_type = "generic"
            updated_trigger_any = cast(Any, updated_trigger)
            if hasattr(updated_trigger_any, "webhook_type"):
                wt = updated_trigger_any.webhook_type
                channel_type = wt.value if hasattr(wt, "value") else str(wt)
            elif (
                hasattr(updated_trigger_any, "data_extractor")
                and updated_trigger_any.data_extractor
            ):
                channel_type = str(updated_trigger_any.data_extractor).removesuffix("_polling")
            secret_name = channel_credential_secret_name(channel_type, trigger_id)
            await secret_manager.set_secret(secret_name, json.dumps(credentials))
            has_creds = True
            await webhook_service.register(
                channel_type=getattr(updated_trigger, "webhook_type", None),
                webhook_id=getattr(updated_trigger, "webhook_id", None),
                credentials=credentials,
            )
            logger.info(f"Updated channel credentials for trigger {trigger_id}")
        elif secret_manager:
            # Check if credentials already exist
            has_creds = await _has_credentials(secret_manager, updated_trigger, trigger_id)

        logger.info(f"Updated trigger {trigger_id}")

        return TriggerResponse.from_domain_model(updated_trigger, has_channel_credentials=has_creds)

    except HTTPException:
        raise
    except TriggerNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except TriggerValidationError as e:
        logger.warning(f"Trigger validation failed: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception(f"Failed to update trigger {trigger_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.delete(
    "/{trigger_id}",
    status_code=204,
    dependencies=[requires("delete", "trigger", id_param="trigger_id")],
)
async def delete_trigger(
    secret_manager: BaseSecretManagerDep,
    trigger_id: UUID,
    user_context: UserContext = Depends(get_user_context),
    trigger_service: TriggerService = Depends(get_trigger_service),
    webhook_service: ChannelWebhookService = Depends(get_channel_webhook_service),
) -> None:
    """Delete a trigger.

    Permanently deletes the specified trigger and all its execution history.
    If it's a cron trigger, the schedule will also be removed.

    Args:
        secret_manager: Injected secret manager, used to read channel credentials.
        trigger_id: The unique identifier of the trigger
        user_context: Authentication context
        trigger_service: Injected trigger service
        webhook_service: Injected service that clears the channel webhook.

    Raises:
        HTTPException: If trigger not found
    """
    try:
        # Best-effort: clear this trigger's provider-side webhook before it goes
        # away. Channel-agnostic — resolve the channel from the trigger, read its
        # stored credentials, and let the service delegate. Never blocks delete.
        try:
            trigger = await trigger_service.get_trigger(trigger_id)
            secret_name = _channel_secret_name(trigger, trigger_id) if trigger else None
            if secret_manager and secret_name:
                raw = await secret_manager.get_secret(secret_name)
                if raw:
                    await webhook_service.deregister(
                        channel_type=getattr(trigger, "webhook_type", None),
                        credentials=json.loads(raw),
                    )
        except Exception as e:
            logger.warning(
                f"Webhook deregistration on delete failed for {trigger_id}: {e}", exc_info=True
            )

        success = await trigger_service.delete_trigger(trigger_id)

        if not success:
            raise HTTPException(status_code=404, detail=f"Trigger {trigger_id} not found")

        logger.info(f"Deleted trigger {trigger_id}")

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to delete trigger {trigger_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.post(
    "/{trigger_id}/enable",
    response_model=dict[str, Any],
    dependencies=[requires("edit", "trigger", id_param="trigger_id")],
)
async def enable_trigger(
    trigger_id: UUID,
    user_context: UserContext = Depends(get_user_context),
    trigger_service: TriggerService = Depends(get_trigger_service),
) -> dict[str, Any]:
    """Enable a trigger.

    Enables the specified trigger, allowing it to execute when conditions are met.
    For cron triggers, this will resume the schedule.

    Args:
        trigger_id: The unique identifier of the trigger
        user_context: Authentication context
        trigger_service: Injected trigger service

    Returns:
        Success status

    Raises:
        HTTPException: If trigger not found
    """
    try:
        success = await trigger_service.enable_trigger(trigger_id)

        if not success:
            raise HTTPException(status_code=404, detail=f"Trigger {trigger_id} not found")

        logger.info(f"Enabled trigger {trigger_id}")

        return {
            "status": "success",
            "message": f"Trigger {trigger_id} enabled successfully",
            "trigger_id": str(trigger_id),
            "is_active": True,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to enable trigger {trigger_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.post(
    "/{trigger_id}/disable",
    response_model=dict[str, Any],
    dependencies=[requires("edit", "trigger", id_param="trigger_id")],
)
async def disable_trigger(
    trigger_id: UUID,
    user_context: UserContext = Depends(get_user_context),
    trigger_service: TriggerService = Depends(get_trigger_service),
) -> dict[str, Any]:
    """Disable a trigger.

    Disables the specified trigger, preventing it from executing.
    For cron triggers, this will pause the schedule.

    Args:
        trigger_id: The unique identifier of the trigger
        user_context: Authentication context
        trigger_service: Injected trigger service

    Returns:
        Success status

    Raises:
        HTTPException: If trigger not found
    """
    try:
        success = await trigger_service.disable_trigger(trigger_id)

        if not success:
            raise HTTPException(status_code=404, detail=f"Trigger {trigger_id} not found")

        logger.info(f"Disabled trigger {trigger_id}")

        return {
            "status": "success",
            "message": f"Trigger {trigger_id} disabled successfully",
            "trigger_id": str(trigger_id),
            "is_active": False,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to disable trigger {trigger_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.get(
    "/{trigger_id}/executions",
    response_model=ExecutionHistoryResponse,
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def get_execution_history(
    trigger_id: UUID,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Number of executions per page"),
    status: str | None = Query(
        None, description="Filter by execution status (success, failed, timeout)"
    ),
    start_time: datetime | None = Query(None, description="Filter executions after this time"),
    end_time: datetime | None = Query(None, description="Filter executions before this time"),
    user_context: UserContext = Depends(get_user_context),
    trigger_service: TriggerService = Depends(get_trigger_service),
    db_session: AsyncSession = Depends(get_db_session),
) -> ExecutionHistoryResponse:
    """Get execution history for a trigger with filtering and pagination.

    Returns paginated execution history for the specified trigger, including
    success/failure status, execution times, and error messages. Supports
    filtering by status and time range.

    Args:
        trigger_id: The unique identifier of the trigger
        page: Page number for pagination
        page_size: Number of executions per page
        status: Optional status filter (success, failed, timeout)
        start_time: Optional start time filter
        end_time: Optional end time filter
        user_context: Authentication context
        trigger_service: Injected trigger service
        db_session: Session used to resolve what each run's task cost

    Returns:
        Paginated execution history

    Raises:
        HTTPException: If trigger not found or invalid parameters
    """
    try:
        # Check if trigger exists
        trigger = await trigger_service.get_trigger(trigger_id)
        if not trigger:
            raise HTTPException(status_code=404, detail=f"Trigger {trigger_id} not found")

        # Validate status filter
        status_enum = None
        if status:
            from agentarea_triggers.domain.enums import ExecutionStatus

            try:
                status_enum = ExecutionStatus(status.upper())
            except ValueError as e:
                raise HTTPException(status_code=400, detail=f"Invalid status: {status}") from e

        # Calculate offset
        offset = (page - 1) * page_size

        # Get execution history with filtering
        executions, total = await trigger_service.get_execution_history_paginated(
            trigger_id=trigger_id,
            status=status_enum,
            start_time=start_time,
            end_time=end_time,
            limit=page_size,
            offset=offset,
        )

        # Check if there's a next page
        has_next = (offset + page_size) < total

        # Convert to response models
        execution_responses = [
            TriggerExecutionResponse.from_domain_model(execution) for execution in executions
        ]

        # What each run cost: the spend sits on the task it created, so it is
        # resolved here rather than stored on the execution row.
        costs = await _costs_by_task(
            db_session,
            user_context.workspace_id,
            [response.task_id for response in execution_responses if response.task_id],
        )
        for response in execution_responses:
            if response.task_id is not None:
                response.cost_usd = costs.get(response.task_id)

        return ExecutionHistoryResponse(
            executions=execution_responses,
            total=total,
            page=page,
            page_size=page_size,
            has_next=has_next,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get execution history for trigger {trigger_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.get(
    "/{trigger_id}/status",
    response_model=TriggerStatusResponse,
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def get_trigger_status(
    trigger_id: UUID,
    user_context: UserContext = Depends(get_user_context),
    trigger_service: TriggerService = Depends(get_trigger_service),
) -> TriggerStatusResponse:
    """Get trigger status and schedule information.

    Returns detailed status information about the trigger, including execution
    status, rate limiting, and schedule information for cron triggers.

    Args:
        trigger_id: The unique identifier of the trigger
        user_context: Authentication context
        trigger_service: Injected trigger service

    Returns:
        Trigger status information

    Raises:
        HTTPException: If trigger not found
    """
    try:
        # Get trigger
        trigger = await trigger_service.get_trigger(trigger_id)
        if not trigger:
            raise HTTPException(status_code=404, detail=f"Trigger {trigger_id} not found")

        # Get schedule info for cron triggers
        schedule_info = None
        if hasattr(trigger, "cron_expression"):
            schedule_info = await trigger_service.get_cron_schedule_info(trigger_id)

        return TriggerStatusResponse(
            trigger_id=trigger_id,
            is_active=trigger.is_active,
            last_execution_at=trigger.last_execution_at,
            consecutive_failures=trigger.consecutive_failures,
            should_disable_due_to_failures=trigger.should_disable_due_to_failures(),
            schedule_info=schedule_info,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get trigger status for {trigger_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.get(
    "/{trigger_id}/metrics",
    response_model=ExecutionMetricsResponse,
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def get_execution_metrics(
    trigger_id: UUID,
    hours: int | None = Query(
        None,
        ge=1,
        le=8760,
        description="Time period in hours (max 1 year). Omit for the trigger's whole history.",
    ),
    user_context: UserContext = Depends(get_user_context),
    trigger_service: TriggerService = Depends(get_trigger_service),
    db_session: AsyncSession = Depends(get_db_session),
) -> ExecutionMetricsResponse:
    """Get execution metrics for a trigger.

    Returns aggregated counts, success rate, execution time and spend. Spend is
    the cost of the tasks those runs created, joined at read time — a run is
    recorded when its task starts, the bill accrues afterwards.

    Args:
        trigger_id: The unique identifier of the trigger
        hours: Time period in hours to analyze; omitted means the whole history
        user_context: Authentication context
        trigger_service: Injected trigger service
        db_session: Session used for the spend join

    Returns:
        Execution metrics for the trigger

    Raises:
        HTTPException: If trigger not found
    """
    try:
        # Check if trigger exists
        trigger = await trigger_service.get_trigger(trigger_id)
        if not trigger:
            raise HTTPException(status_code=404, detail=f"Trigger {trigger_id} not found")

        # Get execution metrics
        metrics = await trigger_service.get_execution_metrics(trigger_id, hours)
        total_cost, costed = await _trigger_spend(
            db_session, user_context.workspace_id, trigger_id, hours
        )

        return ExecutionMetricsResponse(
            trigger_id=trigger_id,
            total_cost_usd=round(total_cost, 6),
            avg_cost_usd=round(total_cost / costed, 6) if costed else 0.0,
            costed_executions=costed,
            **metrics,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get execution metrics for trigger {trigger_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.get(
    "/{trigger_id}/timeline",
    response_model=ExecutionTimelineResponse,
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def get_execution_timeline(
    trigger_id: UUID,
    hours: int = Query(24, ge=1, le=168, description="Time period in hours (max 7 days)"),
    bucket_size_minutes: int = Query(60, ge=5, le=1440, description="Time bucket size in minutes"),
    user_context: UserContext = Depends(get_user_context),
    trigger_service: TriggerService = Depends(get_trigger_service),
) -> ExecutionTimelineResponse:
    """Get execution timeline for a trigger.

    Returns time-bucketed execution counts and success rates for visualization
    and trend analysis.

    Args:
        trigger_id: The unique identifier of the trigger
        hours: Time period in hours to analyze (default 24, max 168)
        bucket_size_minutes: Size of time buckets in minutes (default 60)
        user_context: Authentication context
        trigger_service: Injected trigger service

    Returns:
        Execution timeline data

    Raises:
        HTTPException: If trigger not found
    """
    try:
        # Check if trigger exists
        trigger = await trigger_service.get_trigger(trigger_id)
        if not trigger:
            raise HTTPException(status_code=404, detail=f"Trigger {trigger_id} not found")

        # Get execution timeline
        timeline = await trigger_service.get_execution_timeline(
            trigger_id, hours, bucket_size_minutes
        )

        return ExecutionTimelineResponse(
            trigger_id=trigger_id, period_hours=hours, timeline=timeline
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get execution timeline for trigger {trigger_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.get(
    "/{trigger_id}/correlations",
    response_model=ExecutionCorrelationResponse,
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def get_execution_correlations(
    trigger_id: UUID,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Number of executions per page"),
    user_context: UserContext = Depends(get_user_context),
    trigger_service: TriggerService = Depends(get_trigger_service),
) -> ExecutionCorrelationResponse:
    """Get execution correlation data for a trigger.

    Returns execution data with correlation information to created tasks
    and workflows for debugging and monitoring purposes.

    Args:
        trigger_id: The unique identifier of the trigger
        page: Page number for pagination
        page_size: Number of executions per page
        user_context: Authentication context
        trigger_service: Injected trigger service

    Returns:
        Execution correlation data

    Raises:
        HTTPException: If trigger not found
    """
    try:
        # Check if trigger exists
        trigger = await trigger_service.get_trigger(trigger_id)
        if not trigger:
            raise HTTPException(status_code=404, detail=f"Trigger {trigger_id} not found")

        # Calculate offset
        offset = (page - 1) * page_size

        # Get execution correlations
        correlations, total = await trigger_service.get_execution_correlations(
            trigger_id, page_size, offset
        )

        # Check if there's a next page
        has_next = (offset + page_size) < total

        return ExecutionCorrelationResponse(
            executions=correlations, total=total, page=page, page_size=page_size, has_next=has_next
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get execution correlations for trigger {trigger_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.post(
    "/{trigger_id}/execute",
    response_model=dict[str, Any],
    dependencies=[requires("edit", "trigger", id_param="trigger_id")],
)
async def execute_trigger(
    trigger_id: UUID,
    request: TriggerExecuteRequest,
    trigger_service: TriggerService = Depends(get_trigger_service),
) -> dict[str, Any]:
    """Execute a trigger with the provided event data.

    Builds trigger data from the events and channel origin, then creates and
    submits a task for agent execution.

    Authorization is the caller's session plus the workspace-scoped trigger
    lookup: a trigger in another workspace is simply not found. This used to sit
    on the public router behind an ``X-Internal-Token`` check that skipped
    itself whenever the secret was unset — which was every deployment, since
    nothing ever sent that header.

    Args:
        trigger_id: The unique identifier of the trigger
        request: Events and channel origin data
        trigger_service: Injected trigger service

    Returns:
        Execution result with task ID

    Raises:
        HTTPException: If trigger not found or execution fails
    """
    try:
        trigger_data: dict[str, Any] = {
            "events": request.events,
            "channel_origin": request.channel_origin,
        }

        execution = await trigger_service.execute_trigger(trigger_id, trigger_data)

        if execution is None:
            return {
                "status": "skipped",
                "trigger_id": str(trigger_id),
            }

        return {
            "status": "success",
            "trigger_id": str(trigger_id),
            "execution_id": str(execution.id) if execution else None,
            "task_id": str(execution.task_id) if execution and execution.task_id else None,
        }

    except TriggerNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Failed to execute trigger {trigger_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.post(
    "/{trigger_id}/run",
    response_model=TriggerRunResponse,
    dependencies=[requires("edit", "trigger", id_param="trigger_id")],
)
async def run_trigger_now(
    trigger_id: UUID,
    trigger_service: TriggerService = Depends(get_trigger_service),
    user_context: UserContext = Depends(get_user_context),
) -> TriggerRunResponse:
    """Fire a trigger once, now, because a person asked for it.

    Distinct from ``/execute``, which replays a real event: this carries no event
    data and records the caller in ``fired_by``, so the run is visibly a manual
    one and the task it creates belongs to the caller rather than to whoever
    created the trigger.

    The run is otherwise faithful to a real one -- the trigger's conditions are
    still evaluated, and a run they reject comes back ``skipped`` with the reason
    rather than being forced through. A trigger that is switched off still runs:
    ``is_active`` governs the schedule, not a person asking for one run.

    Returns:
        The execution, and the task id to watch when one was created.
    """
    if not user_context.user_id:
        raise HTTPException(status_code=401, detail="Authenticated user required")

    try:
        execution = await trigger_service.execute_trigger(
            trigger_id, {"events": [], "channel_origin": {}}, fired_by=user_context.user_id
        )
    except TriggerNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Failed to run trigger {trigger_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from e

    # No execution record at all means the run never happened and nothing said
    # why. Reporting that as success would put a "started" toast over nothing.
    if execution is None:
        raise HTTPException(status_code=500, detail="Trigger run produced no execution")

    task_id = getattr(execution, "task_id", None)
    return TriggerRunResponse(
        status="started" if task_id else "skipped",
        trigger_id=trigger_id,
        execution_id=execution.id,
        task_id=task_id,
        reason=getattr(execution, "error_message", None),
    )
