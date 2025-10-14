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

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from agentarea_api.api.deps.services import (
    get_trigger_health_check,
    get_trigger_service,
)
from agentarea_api.api.v1.a2a_auth import A2AAuthContext, require_a2a_execute_auth
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_triggers.domain.enums import TriggerType, WebhookType
from agentarea_triggers.domain.models import (
    TriggerCreate,
    TriggerUpdate,
)
from agentarea_triggers.trigger_service import (
    TriggerNotFoundError,
    TriggerService,
    TriggerValidationError,
)
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

TRIGGERS_AVAILABLE = True

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

    @classmethod
    def from_domain_model(cls, trigger: Any) -> "TriggerResponse":
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
                }
            )

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


class TriggerCreateRequest(BaseModel):
    """Request model for creating a trigger."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="", max_length=1000)
    agent_id: UUID
    trigger_type: str
    task_parameters: dict[str, Any] = Field(default_factory=dict)
    conditions: dict[str, Any] = Field(default_factory=dict)

    # Business logic safety
    failure_threshold: int = Field(default=5, ge=1, le=100)

    # Cron-specific fields
    cron_expression: str | None = None
    timezone: str = Field(default="UTC")

    # Webhook-specific fields
    webhook_id: str | None = None
    allowed_methods: list[str] = Field(default_factory=lambda: ["POST"])
    webhook_type: str = Field(default="generic")
    validation_rules: dict[str, Any] = Field(default_factory=dict)
    webhook_config: dict[str, Any] | None = None

    @field_validator("trigger_type")
    @classmethod
    def validate_trigger_type(cls, v: str) -> str:
        """Validate trigger type."""
        valid_types = ["cron", "webhook"]
        if v.lower() not in valid_types:
            raise ValueError(f"Invalid trigger type. Must be one of: {valid_types}")
        return v.lower()

    @field_validator("webhook_type")
    @classmethod
    def validate_webhook_type(cls, v: str) -> str:
        """Validate webhook type."""
        valid_types = ["generic", "telegram", "slack", "github", "discord", "stripe"]
        if v.lower() not in valid_types:
            raise ValueError(f"Invalid webhook type. Must be one of: {valid_types}")
        return v.lower()


class TriggerUpdateRequest(BaseModel):
    """Request model for updating a trigger."""

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=1000)
    is_active: bool | None = None
    task_parameters: dict[str, Any] | None = None
    conditions: dict[str, Any] | None = None

    # Business logic safety
    failure_threshold: int | None = Field(None, ge=1, le=100)

    # Cron-specific fields
    cron_expression: str | None = None
    timezone: str | None = None

    # Webhook-specific fields
    allowed_methods: list[str] | None = None
    webhook_type: str | None = None
    validation_rules: dict[str, Any] | None = None
    webhook_config: dict[str, Any] | None = None

    @field_validator("webhook_type")
    @classmethod
    def validate_webhook_type(cls, v: str | None) -> str | None:
        """Validate webhook type."""
        if v is None:
            return v
        valid_types = ["generic", "telegram", "slack", "github", "discord", "stripe"]
        if v.lower() not in valid_types:
            raise ValueError(f"Invalid webhook type. Must be one of: {valid_types}")
        return v.lower()


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


# Utility Functions


def _check_triggers_availability():
    """Check if triggers service is available and raise appropriate error."""
    if not TRIGGERS_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="Triggers service is not available. Please check system configuration.",
        )


def _convert_to_domain_create(request: TriggerCreateRequest, created_by: str) -> Any:
    """Convert API request to domain model for creation."""
    if not TRIGGERS_AVAILABLE:
        return None

    # Import here to avoid issues when triggers not available

    # Convert string enums to domain enums
    trigger_type = TriggerType.CRON if request.trigger_type == "cron" else TriggerType.WEBHOOK
    webhook_type = (
        WebhookType(request.webhook_type) if request.webhook_type else WebhookType.GENERIC
    )

    return TriggerCreate(
        name=request.name,
        description=request.description,
        agent_id=request.agent_id,
        trigger_type=trigger_type,
        task_parameters=request.task_parameters,
        conditions=request.conditions,
        created_by=created_by,
        failure_threshold=request.failure_threshold,
        cron_expression=request.cron_expression,
        timezone=request.timezone,
        webhook_id=request.webhook_id,
        allowed_methods=request.allowed_methods,
        webhook_type=webhook_type,
        validation_rules=request.validation_rules,
        webhook_config=request.webhook_config,
    )


def _convert_to_domain_update(request: TriggerUpdateRequest) -> Any:
    """Convert API request to domain model for update."""
    if not TRIGGERS_AVAILABLE:
        return None

    # Import here to avoid issues when triggers not available

    # Convert webhook type if provided
    webhook_type = None
    if request.webhook_type:
        webhook_type = WebhookType(request.webhook_type)

    return TriggerUpdate(
        name=request.name,
        description=request.description,
        is_active=request.is_active,
        task_parameters=request.task_parameters,
        conditions=request.conditions,
        failure_threshold=request.failure_threshold,
        cron_expression=request.cron_expression,
        timezone=request.timezone,
        allowed_methods=request.allowed_methods,
        webhook_type=webhook_type,
        validation_rules=request.validation_rules,
        webhook_config=request.webhook_config,
    )


# API Endpoints


@router.post("/", response_model=TriggerResponse, status_code=201)
async def create_trigger(
    request: TriggerCreateRequest,
    auth_context: A2AAuthContext = Depends(require_a2a_execute_auth),
    trigger_service: TriggerService = Depends(get_trigger_service),
) -> TriggerResponse:
    """Create a new trigger.

    Creates a new trigger with the specified configuration. The trigger will be
    validated and, if it's a cron trigger, automatically scheduled.

    Args:
        request: Trigger creation request data
        auth_context: Authentication context
        trigger_service: Injected trigger service

    Returns:
        The created trigger

    Raises:
        HTTPException: If validation fails or creation errors occur
    """
    _check_triggers_availability()

    try:
        # Convert API request to domain model
        created_by = auth_context.user_id or "api_user"
        trigger_data = _convert_to_domain_create(request, created_by)

        # Create trigger
        trigger = await trigger_service.create_trigger(trigger_data)

        logger.info(f"Created trigger {trigger.id} for agent {trigger.agent_id}")

        return TriggerResponse.from_domain_model(trigger)

    except TriggerValidationError as e:
        logger.warning(f"Trigger validation failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create trigger: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create trigger: {e!s}")


@router.get("/", response_model=list[TriggerResponse])
async def list_triggers(
    agent_id: UUID | None = Query(None, description="Filter by agent ID"),
    trigger_type: str | None = Query(None, description="Filter by trigger type (cron, webhook)"),
    active_only: bool = Query(False, description="Only return active triggers"),
    created_by: str | None = Query(
        None, description="Filter by creator: 'me' for current user's triggers only"
    ),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of triggers to return"),
    auth_context: A2AAuthContext = Depends(require_a2a_execute_auth),
    trigger_service: TriggerService = Depends(get_trigger_service),
) -> list[TriggerResponse]:
    """List triggers with optional filtering.

    Returns a list of triggers that match the specified criteria. Supports
    filtering by agent ID, trigger type, and active status.

    Args:
        agent_id: Optional agent ID filter
        trigger_type: Optional trigger type filter
        active_only: Whether to only return active triggers
        limit: Maximum number of triggers to return
        auth_context: Authentication context
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

        # Determine if we should filter by creator
        creator_scoped = created_by == "me"

        # List triggers
        triggers = await trigger_service.list_triggers(
            agent_id=agent_id,
            trigger_type=domain_trigger_type,
            active_only=active_only,
            creator_scoped=creator_scoped,
            limit=limit,
        )

        logger.info(f"Listed {len(triggers)} triggers")

        return [TriggerResponse.from_domain_model(trigger) for trigger in triggers]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list triggers: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list triggers: {e!s}")


@router.get("/{trigger_id}", response_model=TriggerResponse)
async def get_trigger(
    trigger_id: UUID,
    auth_context: A2AAuthContext = Depends(require_a2a_execute_auth),
    trigger_service: TriggerService = Depends(get_trigger_service),
) -> TriggerResponse:
    """Get a specific trigger by ID.

    Args:
        trigger_id: The unique identifier of the trigger
        auth_context: Authentication context
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
        raise HTTPException(status_code=500, detail=f"Failed to get trigger: {e!s}")


@router.put("/{trigger_id}", response_model=TriggerResponse)
async def update_trigger(
    trigger_id: UUID,
    request: TriggerUpdateRequest,
    auth_context: A2AAuthContext = Depends(require_a2a_execute_auth),
    trigger_service: TriggerService = Depends(get_trigger_service),
) -> TriggerResponse:
    """Update an existing trigger.

    Updates the specified trigger with the provided data. Only non-null fields
    in the request will be updated.

    Args:
        trigger_id: The unique identifier of the trigger
        request: Trigger update request data
        auth_context: Authentication context
        trigger_service: Injected trigger service

    Returns:
        The updated trigger

    Raises:
        HTTPException: If trigger not found or validation fails
    """
    _check_triggers_availability()

    try:
        # Convert API request to domain model
        trigger_update = _convert_to_domain_update(request)

        # Update trigger
        updated_trigger = await trigger_service.update_trigger(trigger_id, trigger_update)

        logger.info(f"Updated trigger {trigger_id}")

        return TriggerResponse.from_domain_model(updated_trigger)

    except TriggerNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except TriggerValidationError as e:
        logger.warning(f"Trigger validation failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to update trigger {trigger_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update trigger: {e!s}")


@router.delete("/{trigger_id}", status_code=204)
async def delete_trigger(
    trigger_id: UUID,
    auth_context: A2AAuthContext = Depends(require_a2a_execute_auth),
    trigger_service: TriggerService = Depends(get_trigger_service),
) -> None:
    """Delete a trigger.

    Permanently deletes the specified trigger and all its execution history.
    If it's a cron trigger, the schedule will also be removed.

    Args:
        trigger_id: The unique identifier of the trigger
        auth_context: Authentication context
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
        raise HTTPException(status_code=500, detail=f"Failed to delete trigger: {e!s}")


@router.post("/{trigger_id}/enable", response_model=dict[str, Any])
async def enable_trigger(
    trigger_id: UUID,
    auth_context: A2AAuthContext = Depends(require_a2a_execute_auth),
    trigger_service: TriggerService = Depends(get_trigger_service),
) -> dict[str, Any]:
    """Enable a trigger.

    Enables the specified trigger, allowing it to execute when conditions are met.
    For cron triggers, this will resume the schedule.

    Args:
        trigger_id: The unique identifier of the trigger
        auth_context: Authentication context
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
        raise HTTPException(status_code=500, detail=f"Failed to enable trigger: {e!s}")


@router.post("/{trigger_id}/disable", response_model=dict[str, Any])
async def disable_trigger(
    trigger_id: UUID,
    auth_context: A2AAuthContext = Depends(require_a2a_execute_auth),
    trigger_service: TriggerService = Depends(get_trigger_service),
) -> dict[str, Any]:
    """Disable a trigger.

    Disables the specified trigger, preventing it from executing.
    For cron triggers, this will pause the schedule.

    Args:
        trigger_id: The unique identifier of the trigger
        auth_context: Authentication context
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
        raise HTTPException(status_code=500, detail=f"Failed to disable trigger: {e!s}")


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
    auth_context: A2AAuthContext = Depends(require_a2a_execute_auth),
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
        auth_context: Authentication context
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
                except ValueError:
                    raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

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
        raise HTTPException(status_code=500, detail=f"Failed to get execution history: {e!s}")


@router.get("/{trigger_id}/status", response_model=TriggerStatusResponse)
async def get_trigger_status(
    trigger_id: UUID,
    auth_context: A2AAuthContext = Depends(require_a2a_execute_auth),
    trigger_service: TriggerService = Depends(get_trigger_service),
) -> TriggerStatusResponse:
    """Get trigger status and schedule information.

    Returns detailed status information about the trigger, including execution
    status, rate limiting, and schedule information for cron triggers.

    Args:
        trigger_id: The unique identifier of the trigger
        auth_context: Authentication context
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
        raise HTTPException(status_code=500, detail=f"Failed to get trigger status: {e!s}")


@router.get("/{trigger_id}/metrics", response_model=ExecutionMetricsResponse)
async def get_execution_metrics(
    trigger_id: UUID,
    hours: int = Query(24, ge=1, le=168, description="Time period in hours (max 7 days)"),
    auth_context: A2AAuthContext = Depends(require_a2a_execute_auth),
    trigger_service: TriggerService = Depends(get_trigger_service),
) -> ExecutionMetricsResponse:
    """Get execution metrics for a trigger.

    Returns aggregated metrics including success rate, average execution time,
    and failure counts for the specified time period.

    Args:
        trigger_id: The unique identifier of the trigger
        hours: Time period in hours to analyze (default 24, max 168)
        auth_context: Authentication context
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
        raise HTTPException(status_code=500, detail=f"Failed to get execution metrics: {e!s}")


@router.get("/{trigger_id}/timeline", response_model=ExecutionTimelineResponse)
async def get_execution_timeline(
    trigger_id: UUID,
    hours: int = Query(24, ge=1, le=168, description="Time period in hours (max 7 days)"),
    bucket_size_minutes: int = Query(60, ge=5, le=1440, description="Time bucket size in minutes"),
    auth_context: A2AAuthContext = Depends(require_a2a_execute_auth),
    trigger_service: TriggerService = Depends(get_trigger_service),
) -> ExecutionTimelineResponse:
    """Get execution timeline for a trigger.

    Returns time-bucketed execution counts and success rates for visualization
    and trend analysis.

    Args:
        trigger_id: The unique identifier of the trigger
        hours: Time period in hours to analyze (default 24, max 168)
        bucket_size_minutes: Size of time buckets in minutes (default 60)
        auth_context: Authentication context
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
        raise HTTPException(status_code=500, detail=f"Failed to get execution timeline: {e!s}")


@router.get("/{trigger_id}/correlations", response_model=ExecutionCorrelationResponse)
async def get_execution_correlations(
    trigger_id: UUID,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Number of executions per page"),
    auth_context: A2AAuthContext = Depends(require_a2a_execute_auth),
    trigger_service: TriggerService = Depends(get_trigger_service),
) -> ExecutionCorrelationResponse:
    """Get execution correlation data for a trigger.

    Returns execution data with correlation information to created tasks
    and workflows for debugging and monitoring purposes.

    Args:
        trigger_id: The unique identifier of the trigger
        page: Page number for pagination
        page_size: Number of executions per page
        auth_context: Authentication context
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
        raise HTTPException(status_code=500, detail=f"Failed to get execution correlations: {e!s}")


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

    except Exception as e:
        logger.error(f"Triggers health check failed: {e}")
        return {
            "overall_status": "unhealthy",
            "service": "triggers",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat(),
            "components": {},
        }
