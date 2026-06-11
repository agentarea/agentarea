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

import json
import logging
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from agentarea_api.api.deps.services import (
    BaseSecretManagerDep,
    get_trigger_health_check,
    get_trigger_service,
)
from agentarea_common.auth.dependencies import UserContext, get_user_context
from agentarea_triggers.domain.channel_events import CHANNEL_EVENTS, get_trigger_catalog
from agentarea_triggers.schemas.dto import TriggerCreate, TriggerUpdate
from agentarea_triggers.trigger_service import (
    TriggerNotFoundError,
    TriggerService,
    TriggerValidationError,
)
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

TRIGGERS_AVAILABLE = True

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/triggers", tags=["triggers"])

# Public router for endpoints that don't require authentication
# Used by internal services (e.g., Go event-service) for trigger execution
public_router = APIRouter(prefix="/triggers", tags=["triggers"])


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
    created_at: datetime
    updated_at: datetime
    created_by: str

    # Business logic safety
    failure_threshold: int
    consecutive_failures: int
    last_execution_at: datetime | None = None

    # Type-specific fields (optional)
    cron_expression: str | None = None
    timezone: str | None = None
    next_run_time: datetime | None = None
    webhook_id: str | None = None
    allowed_methods: list[str] | None = None
    webhook_type: str | None = None
    validation_rules: dict[str, Any] | None = None
    webhook_config: dict[str, Any] | None = None
    event_types: list[str] = Field(default_factory=list)

    # Poll-based extractor type (e.g., "mailslurper")
    data_extractor: str | None = None

    # Channel credentials indicator (actual credentials never returned)
    has_channel_credentials: bool = False

    @classmethod
    def from_domain_model(
        cls, trigger: Any, has_channel_credentials: bool = False
    ) -> "TriggerResponse":
        """Create response from domain model."""
        if not TRIGGERS_AVAILABLE:
            # Return mock response when triggers not available
            return cls(
                id=UUID("00000000-0000-0000-0000-000000000000"),
                name="Mock Trigger",
                description="Triggers service not available",
                agent_id=UUID("00000000-0000-0000-0000-000000000000"),
                trigger_type="mock",
                is_active=False,
                task_parameters={},
                conditions={},
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                created_by="system",
                failure_threshold=5,
                consecutive_failures=0,
            )

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
                    "validation_rules": trigger.validation_rules,
                    "webhook_config": trigger.webhook_config,
                    "event_types": getattr(trigger, "event_types", []) or [],
                }
            )

        response_data["has_channel_credentials"] = has_channel_credentials

        return cls(**response_data)


class TriggerExecutionResponse(BaseModel):
    """Response model for trigger execution data."""

    id: UUID
    trigger_id: UUID
    executed_at: datetime
    status: str
    task_id: UUID | None = None
    execution_time_ms: int
    error_message: str | None = None
    trigger_data: dict[str, Any]
    workflow_id: str | None = None
    run_id: str | None = None

    @classmethod
    def from_domain_model(cls, execution: Any) -> "TriggerExecutionResponse":
        """Create response from domain model."""
        if not TRIGGERS_AVAILABLE:
            # Return mock response when triggers not available
            return cls(
                id=UUID("00000000-0000-0000-0000-000000000000"),
                trigger_id=UUID("00000000-0000-0000-0000-000000000000"),
                executed_at=datetime.utcnow(),
                status="failed",
                execution_time_ms=0,
                error_message="Triggers service not available",
                trigger_data={},
            )

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
        )


class TriggerStatusResponse(BaseModel):
    """Response model for trigger status information."""

    trigger_id: UUID
    is_active: bool
    last_execution_at: datetime | None = None
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
    period_hours: int
    total_executions: int
    successful_executions: int
    failed_executions: int
    timeout_executions: int
    success_rate: float
    failure_rate: float
    avg_execution_time_ms: float
    min_execution_time_ms: int
    max_execution_time_ms: int


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


# Utility Functions


def _check_triggers_availability():
    """Check if triggers service is available and raise appropriate error."""
    if not TRIGGERS_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="Triggers service is not available. Please check system configuration.",
        )


async def _has_credentials(secret_manager: Any, trigger: Any, trigger_id: UUID) -> bool:
    """Check if channel credentials exist for a trigger."""
    channel_type = "generic"
    if hasattr(trigger, "webhook_type"):
        wt = trigger.webhook_type
        channel_type = wt.value if hasattr(wt, "value") else str(wt)
    secret_name = f"channel_cred:{channel_type}:{trigger_id}"
    raw = await secret_manager.get_secret(secret_name)
    return raw is not None


# API Endpoints


@router.get("/catalog")
async def get_catalog(
    user_context: UserContext = Depends(get_user_context),
) -> list[dict[str, Any]]:
    """Get the trigger catalog — available trigger types with metadata and events."""
    return get_trigger_catalog()


@router.get("/channels/events")
async def get_channel_events(
    user_context: UserContext = Depends(get_user_context),
) -> dict[str, list[str]]:
    """Get supported event types for all channels.
    Returns a mapping of channel type to list of event types.
    """
    return CHANNEL_EVENTS


@router.post("/", response_model=TriggerResponse, status_code=201)
async def create_trigger(
    secret_manager: BaseSecretManagerDep,
    payload: TriggerCreate = Body(...),
    user_context: UserContext = Depends(get_user_context),
    trigger_service: TriggerService = Depends(get_trigger_service),
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

    Returns:
        The created trigger.

    Raises:
        HTTPException: If validation fails or creation errors occur.
    """
    _check_triggers_availability()

    try:
        if not user_context.user_id:
            raise HTTPException(status_code=400, detail="User ID is required to create a trigger")

        # Convert DTO -> domain create. Done up-front so we can fold polling
        # channel credentials into ``data_extractor_config`` before persisting.
        trigger_data = payload.to_domain(
            created_by=user_context.user_id,
            workspace_id=user_context.workspace_id,
        )

        # For polling extractors, merge credentials into extractor config
        # so the Go polling service can read them (e.g. bot_token for Telegram).
        if trigger_data.data_extractor and payload.channel_credentials:
            trigger_data.data_extractor_config = {
                **(trigger_data.data_extractor_config or {}),
                **payload.channel_credentials,
            }

        # Create trigger
        trigger = await trigger_service.create_trigger(trigger_data)

        # Also store credentials encrypted in secret store for Python outbound delivery
        has_creds = False
        if payload.channel_credentials and secret_manager:
            # Channel type for secret key: use webhook_type or derive from data_extractor.
            # Extractor names like "mailslurper" map to channel type via suffix stripping.
            extractor = payload.data_extractor or ""
            channel_type = payload.webhook_type or extractor.removesuffix("_polling") or "generic"
            secret_name = f"channel_cred:{channel_type}:{trigger.id}"
            await secret_manager.set_secret(secret_name, json.dumps(payload.channel_credentials))
            has_creds = True
            logger.info(f"Stored channel credentials for trigger {trigger.id}")

        logger.info(f"Created trigger {trigger.id} for agent {trigger.agent_id}")

        return TriggerResponse.from_domain_model(trigger, has_channel_credentials=has_creds)

    except TriggerValidationError as e:
        logger.warning(f"Trigger validation failed: {e}")
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Failed to create trigger: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.get("/", response_model=list[TriggerResponse])
async def list_triggers(
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
        agent_id: Optional agent ID filter
        trigger_type: Optional trigger type filter
        active_only: Whether to only return active triggers
        limit: Maximum number of triggers to return
        user_context: Authentication context
        trigger_service: Injected trigger service

    Returns:
        List of triggers matching the criteria
    """
    _check_triggers_availability()

    try:
        # Convert string trigger type to domain enum if provided
        domain_trigger_type = None
        if trigger_type:
            if not TRIGGERS_AVAILABLE:
                domain_trigger_type = None
            else:
                from agentarea_triggers.domain.enums import TriggerType

                if trigger_type.lower() == "cron":
                    domain_trigger_type = TriggerType.CRON
                elif trigger_type.lower() == "webhook":
                    domain_trigger_type = TriggerType.WEBHOOK
                else:
                    raise HTTPException(
                        status_code=400, detail=f"Invalid trigger type: {trigger_type}"
                    )

        # List triggers
        triggers = await trigger_service.list_triggers(
            agent_id=agent_id,
            trigger_type=domain_trigger_type,
            active_only=active_only,
            creator_scoped=False,
            limit=limit,
        )

        logger.info(f"Listed {len(triggers)} triggers")

        return [TriggerResponse.from_domain_model(trigger) for trigger in triggers]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list triggers: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


# Health check endpoint
@router.get("/health", response_model=dict[str, Any])
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
        if not TRIGGERS_AVAILABLE:
            return {
                "overall_status": "unavailable",
                "service": "triggers",
                "message": "Triggers service not available",
                "timestamp": datetime.utcnow().isoformat(),
                "components": {},
            }

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


@router.get("/{trigger_id}", response_model=TriggerResponse)
async def get_trigger(
    trigger_id: UUID,
    user_context: UserContext = Depends(get_user_context),
    trigger_service: TriggerService = Depends(get_trigger_service),
) -> TriggerResponse:
    """Get a specific trigger by ID.

    Args:
        trigger_id: The unique identifier of the trigger
        user_context: Authentication context
        trigger_service: Injected trigger service

    Returns:
        The trigger data

    Raises:
        HTTPException: If trigger not found
    """
    _check_triggers_availability()

    try:
        trigger = await trigger_service.get_trigger(trigger_id)

        if not trigger:
            raise HTTPException(status_code=404, detail=f"Trigger {trigger_id} not found")

        return TriggerResponse.from_domain_model(trigger)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get trigger {trigger_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.put("/{trigger_id}", response_model=TriggerResponse)
async def update_trigger(
    trigger_id: UUID,
    secret_manager: BaseSecretManagerDep,
    payload: TriggerUpdate = Body(...),
    user_context: UserContext = Depends(get_user_context),
    trigger_service: TriggerService = Depends(get_trigger_service),
) -> TriggerResponse:
    """Update an existing trigger.

    Updates the specified trigger with the provided data. Only non-null fields
    in the request will be updated. If channel_credentials are provided,
    they replace the existing credentials in the secret store.

    Args:
        trigger_id: The unique identifier of the trigger.
        payload: Trigger update DTO (single source of truth shared with MCP toolset).
        user_context: Authentication context.
        trigger_service: Injected trigger service.
        secret_manager: Injected secret manager for credential storage.

    Returns:
        The updated trigger.

    Raises:
        HTTPException: If trigger not found or validation fails.
    """
    _check_triggers_availability()

    try:
        trigger_update = payload.to_domain()

        # Update trigger
        updated_trigger = await trigger_service.update_trigger(trigger_id, trigger_update)

        # Update channel credentials if provided
        has_creds = False
        if payload.channel_credentials and secret_manager:
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
            secret_name = f"channel_cred:{channel_type}:{trigger_id}"
            await secret_manager.set_secret(secret_name, json.dumps(payload.channel_credentials))
            has_creds = True
            logger.info(f"Updated channel credentials for trigger {trigger_id}")
        elif secret_manager:
            # Check if credentials already exist
            has_creds = await _has_credentials(secret_manager, updated_trigger, trigger_id)

        logger.info(f"Updated trigger {trigger_id}")

        return TriggerResponse.from_domain_model(updated_trigger, has_channel_credentials=has_creds)

    except TriggerNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except TriggerValidationError as e:
        logger.warning(f"Trigger validation failed: {e}")
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Failed to update trigger {trigger_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.delete("/{trigger_id}", status_code=204)
async def delete_trigger(
    trigger_id: UUID,
    user_context: UserContext = Depends(get_user_context),
    trigger_service: TriggerService = Depends(get_trigger_service),
) -> None:
    """Delete a trigger.

    Permanently deletes the specified trigger and all its execution history.
    If it's a cron trigger, the schedule will also be removed.

    Args:
        trigger_id: The unique identifier of the trigger
        user_context: Authentication context
        trigger_service: Injected trigger service

    Raises:
        HTTPException: If trigger not found
    """
    _check_triggers_availability()

    try:
        success = await trigger_service.delete_trigger(trigger_id)

        if not success:
            raise HTTPException(status_code=404, detail=f"Trigger {trigger_id} not found")

        logger.info(f"Deleted trigger {trigger_id}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete trigger {trigger_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.post("/{trigger_id}/enable", response_model=dict[str, Any])
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
    _check_triggers_availability()

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
        logger.error(f"Failed to enable trigger {trigger_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.post("/{trigger_id}/disable", response_model=dict[str, Any])
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
    _check_triggers_availability()

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
        logger.error(f"Failed to disable trigger {trigger_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.get("/{trigger_id}/executions", response_model=ExecutionHistoryResponse)
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

    Returns:
        Paginated execution history

    Raises:
        HTTPException: If trigger not found or invalid parameters
    """
    _check_triggers_availability()

    try:
        # Check if trigger exists
        trigger = await trigger_service.get_trigger(trigger_id)
        if not trigger:
            raise HTTPException(status_code=404, detail=f"Trigger {trigger_id} not found")

        # Validate status filter
        status_enum = None
        if status:
            if not TRIGGERS_AVAILABLE:
                status_enum = None
            else:
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
        logger.error(f"Failed to get execution history for trigger {trigger_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.get("/{trigger_id}/status", response_model=TriggerStatusResponse)
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
    _check_triggers_availability()

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
        logger.error(f"Failed to get trigger status for {trigger_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.get("/{trigger_id}/metrics", response_model=ExecutionMetricsResponse)
async def get_execution_metrics(
    trigger_id: UUID,
    hours: int = Query(24, ge=1, le=168, description="Time period in hours (max 7 days)"),
    user_context: UserContext = Depends(get_user_context),
    trigger_service: TriggerService = Depends(get_trigger_service),
) -> ExecutionMetricsResponse:
    """Get execution metrics for a trigger.

    Returns aggregated metrics including success rate, average execution time,
    and failure counts for the specified time period.

    Args:
        trigger_id: The unique identifier of the trigger
        hours: Time period in hours to analyze (default 24, max 168)
        user_context: Authentication context
        trigger_service: Injected trigger service

    Returns:
        Execution metrics for the trigger

    Raises:
        HTTPException: If trigger not found
    """
    _check_triggers_availability()

    try:
        # Check if trigger exists
        trigger = await trigger_service.get_trigger(trigger_id)
        if not trigger:
            raise HTTPException(status_code=404, detail=f"Trigger {trigger_id} not found")

        # Get execution metrics
        metrics = await trigger_service.get_execution_metrics(trigger_id, hours)

        return ExecutionMetricsResponse(trigger_id=trigger_id, **metrics)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get execution metrics for trigger {trigger_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.get("/{trigger_id}/timeline", response_model=ExecutionTimelineResponse)
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
    _check_triggers_availability()

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
        logger.error(f"Failed to get execution timeline for trigger {trigger_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.get("/{trigger_id}/correlations", response_model=ExecutionCorrelationResponse)
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
    _check_triggers_availability()

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
        logger.error(f"Failed to get execution correlations for trigger {trigger_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@public_router.post("/{trigger_id}/execute", response_model=dict[str, Any])
async def execute_trigger(
    trigger_id: UUID,
    request: TriggerExecuteRequest,
    trigger_service: TriggerService = Depends(get_trigger_service),
) -> dict[str, Any]:
    """Execute a trigger with the provided event data.

    Called by the Go event service when a polling channel receives new messages.
    Builds trigger data from the events and channel origin, then creates and
    submits a task for agent execution.

    Args:
        trigger_id: The unique identifier of the trigger
        request: Events and channel origin data
        trigger_service: Injected trigger service

    Returns:
        Execution result with task ID

    Raises:
        HTTPException: If trigger not found or execution fails
    """
    _check_triggers_availability()

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
