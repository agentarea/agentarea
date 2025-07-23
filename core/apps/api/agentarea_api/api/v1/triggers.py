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
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from agentarea_api.api.deps.services import get_trigger_service, get_webhook_manager
from agentarea_api.api.v1.a2a_auth import A2AAuthContext, require_a2a_execute_auth

# Conditional imports for trigger system
try:
    from agentarea_triggers.trigger_service import TriggerService, TriggerValidationError, TriggerNotFoundError
    from agentarea_triggers.domain.models import (
        Trigger, CronTrigger, WebhookTrigger, TriggerExecution,
        TriggerCreate, TriggerUpdate
    )
    from agentarea_triggers.domain.enums import TriggerType, ExecutionStatus, WebhookType
    TRIGGERS_AVAILABLE = True
except ImportError as e:
    logger = logging.getLogger(__name__)
    logger.warning(f"Triggers module not available: {e}")
    TRIGGERS_AVAILABLE = False
    # Create dummy classes to prevent import errors
    class TriggerService: pass
    class TriggerValidationError(Exception): pass
    class TriggerNotFoundError(Exception): pass
    class Trigger: pass
    class CronTrigger: pass
    class WebhookTrigger: pass
    class TriggerExecution: pass
    class TriggerCreate: pass
    class TriggerUpdate: pass
    class TriggerType: pass
    class ExecutionStatus: pass
    class WebhookType: pass

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
    task_parameters: Dict[str, Any]
    conditions: Dict[str, Any]
    created_at: datetime
    updated_at: datetime
    created_by: str
    
    # Business logic safety
    failure_threshold: int
    consecutive_failures: int
    last_execution_at: Optional[datetime] = None
    
    # Type-specific fields (optional)
    cron_expression: Optional[str] = None
    timezone: Optional[str] = None
    next_run_time: Optional[datetime] = None
    webhook_id: Optional[str] = None
    allowed_methods: Optional[List[str]] = None
    webhook_type: Optional[str] = None
    validation_rules: Optional[Dict[str, Any]] = None
    webhook_config: Optional[Dict[str, Any]] = None

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
                consecutive_failures=0
            )
        
        # Base fields
        response_data = {
            "id": trigger.id,
            "name": trigger.name,
            "description": trigger.description,
            "agent_id": trigger.agent_id,
            "trigger_type": trigger.trigger_type.value if hasattr(trigger.trigger_type, 'value') else str(trigger.trigger_type),
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
        if hasattr(trigger, 'cron_expression'):
            response_data.update({
                "cron_expression": trigger.cron_expression,
                "timezone": trigger.timezone,
                "next_run_time": getattr(trigger, 'next_run_time', None),
            })
        
        if hasattr(trigger, 'webhook_id'):
            response_data.update({
                "webhook_id": trigger.webhook_id,
                "allowed_methods": trigger.allowed_methods,
                "webhook_type": trigger.webhook_type.value if hasattr(trigger.webhook_type, 'value') else str(trigger.webhook_type),
                "validation_rules": trigger.validation_rules,
                "webhook_config": trigger.webhook_config,
            })
        
        return cls(**response_data)


class TriggerExecutionResponse(BaseModel):
    """Response model for trigger execution data."""
    
    id: UUID
    trigger_id: UUID
    executed_at: datetime
    status: str
    task_id: Optional[UUID] = None
    execution_time_ms: int
    error_message: Optional[str] = None
    trigger_data: Dict[str, Any]
    workflow_id: Optional[str] = None
    run_id: Optional[str] = None

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
                trigger_data={}
            )
        
        return cls(
            id=execution.id,
            trigger_id=execution.trigger_id,
            executed_at=execution.executed_at,
            status=execution.status.value if hasattr(execution.status, 'value') else str(execution.status),
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
    task_parameters: Dict[str, Any] = Field(default_factory=dict)
    conditions: Dict[str, Any] = Field(default_factory=dict)
    
    # Business logic safety
    failure_threshold: int = Field(default=5, ge=1, le=100)
    
    # Cron-specific fields
    cron_expression: Optional[str] = None
    timezone: str = Field(default="UTC")
    
    # Webhook-specific fields
    webhook_id: Optional[str] = None
    allowed_methods: List[str] = Field(default_factory=lambda: ["POST"])
    webhook_type: str = Field(default="generic")
    validation_rules: Dict[str, Any] = Field(default_factory=dict)
    webhook_config: Optional[Dict[str, Any]] = None

    @field_validator('trigger_type')
    @classmethod
    def validate_trigger_type(cls, v: str) -> str:
        """Validate trigger type."""
        valid_types = ["cron", "webhook"]
        if v.lower() not in valid_types:
            raise ValueError(f"Invalid trigger type. Must be one of: {valid_types}")
        return v.lower()

    @field_validator('webhook_type')
    @classmethod
    def validate_webhook_type(cls, v: str) -> str:
        """Validate webhook type."""
        valid_types = ["generic", "telegram", "slack", "github", "discord", "stripe"]
        if v.lower() not in valid_types:
            raise ValueError(f"Invalid webhook type. Must be one of: {valid_types}")
        return v.lower()


class TriggerUpdateRequest(BaseModel):
    """Request model for updating a trigger."""
    
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    is_active: Optional[bool] = None
    task_parameters: Optional[Dict[str, Any]] = None
    conditions: Optional[Dict[str, Any]] = None
    
    # Business logic safety
    failure_threshold: Optional[int] = Field(None, ge=1, le=100)
    
    # Cron-specific fields
    cron_expression: Optional[str] = None
    timezone: Optional[str] = None
    
    # Webhook-specific fields
    allowed_methods: Optional[List[str]] = None
    webhook_type: Optional[str] = None
    validation_rules: Optional[Dict[str, Any]] = None
    webhook_config: Optional[Dict[str, Any]] = None

    @field_validator('webhook_type')
    @classmethod
    def validate_webhook_type(cls, v: Optional[str]) -> Optional[str]:
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
    last_execution_at: Optional[datetime] = None
    consecutive_failures: int
    should_disable_due_to_failures: bool
    
    # Schedule information for cron triggers
    schedule_info: Optional[Dict[str, Any]] = None


class ExecutionHistoryResponse(BaseModel):
    """Response model for paginated execution history."""
    
    executions: List[TriggerExecutionResponse]
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
            detail="Triggers service is not available. Please check system configuration."
        )


def _convert_to_domain_create(request: TriggerCreateRequest, created_by: str) -> Any:
    """Convert API request to domain model for creation."""
    if not TRIGGERS_AVAILABLE:
        return None
    
    # Import here to avoid issues when triggers not available
    from agentarea_triggers.domain.models import TriggerCreate
    from agentarea_triggers.domain.enums import TriggerType, WebhookType
    
    # Convert string enums to domain enums
    trigger_type = TriggerType.CRON if request.trigger_type == "cron" else TriggerType.WEBHOOK
    webhook_type = WebhookType(request.webhook_type) if request.webhook_type else WebhookType.GENERIC
    
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
    from agentarea_triggers.domain.models import TriggerUpdate
    from agentarea_triggers.domain.enums import WebhookType
    
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
    """
    Create a new trigger.
    
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
        raise HTTPException(status_code=500, detail=f"Failed to create trigger: {str(e)}")


@router.get("/", response_model=List[TriggerResponse])
async def list_triggers(
    agent_id: Optional[UUID] = Query(None, description="Filter by agent ID"),
    trigger_type: Optional[str] = Query(None, description="Filter by trigger type (cron, webhook)"),
    active_only: bool = Query(False, description="Only return active triggers"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of triggers to return"),
    auth_context: A2AAuthContext = Depends(require_a2a_execute_auth),
    trigger_service: TriggerService = Depends(get_trigger_service),
) -> List[TriggerResponse]:
    """
    List triggers with optional filtering.
    
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
                    raise HTTPException(status_code=400, detail=f"Invalid trigger type: {trigger_type}")
        
        # List triggers
        triggers = await trigger_service.list_triggers(
            agent_id=agent_id,
            trigger_type=domain_trigger_type,
            active_only=active_only,
            limit=limit
        )
        
        logger.info(f"Listed {len(triggers)} triggers")
        
        return [TriggerResponse.from_domain_model(trigger) for trigger in triggers]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list triggers: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list triggers: {str(e)}")


@router.get("/{trigger_id}", response_model=TriggerResponse)
async def get_trigger(
    trigger_id: UUID,
    auth_context: A2AAuthContext = Depends(require_a2a_execute_auth),
    trigger_service: TriggerService = Depends(get_trigger_service),
) -> TriggerResponse:
    """
    Get a specific trigger by ID.
    
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
        raise HTTPException(status_code=500, detail=f"Failed to get trigger: {str(e)}")


@router.put("/{trigger_id}", response_model=TriggerResponse)
async def update_trigger(
    trigger_id: UUID,
    request: TriggerUpdateRequest,
    auth_context: A2AAuthContext = Depends(require_a2a_execute_auth),
    trigger_service: TriggerService = Depends(get_trigger_service),
) -> TriggerResponse:
    """
    Update an existing trigger.
    
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
        raise HTTPException(status_code=500, detail=f"Failed to update trigger: {str(e)}")


@router.delete("/{trigger_id}", status_code=204)
async def delete_trigger(
    trigger_id: UUID,
    auth_context: A2AAuthContext = Depends(require_a2a_execute_auth),
    trigger_service: TriggerService = Depends(get_trigger_service),
) -> None:
    """
    Delete a trigger.
    
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
        raise HTTPException(status_code=500, detail=f"Failed to delete trigger: {str(e)}")


@router.post("/{trigger_id}/enable", response_model=Dict[str, Any])
async def enable_trigger(
    trigger_id: UUID,
    auth_context: A2AAuthContext = Depends(require_a2a_execute_auth),
    trigger_service: TriggerService = Depends(get_trigger_service),
) -> Dict[str, Any]:
    """
    Enable a trigger.
    
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
            "is_active": True
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to enable trigger {trigger_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to enable trigger: {str(e)}")


@router.post("/{trigger_id}/disable", response_model=Dict[str, Any])
async def disable_trigger(
    trigger_id: UUID,
    auth_context: A2AAuthContext = Depends(require_a2a_execute_auth),
    trigger_service: TriggerService = Depends(get_trigger_service),
) -> Dict[str, Any]:
    """
    Disable a trigger.
    
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
            "is_active": False
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to disable trigger {trigger_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to disable trigger: {str(e)}")


@router.get("/{trigger_id}/executions", response_model=ExecutionHistoryResponse)
async def get_execution_history(
    trigger_id: UUID,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Number of executions per page"),
    auth_context: A2AAuthContext = Depends(require_a2a_execute_auth),
    trigger_service: TriggerService = Depends(get_trigger_service),
) -> ExecutionHistoryResponse:
    """
    Get execution history for a trigger.
    
    Returns paginated execution history for the specified trigger, including
    success/failure status, execution times, and error messages.
    
    Args:
        trigger_id: The unique identifier of the trigger
        page: Page number for pagination
        page_size: Number of executions per page
        auth_context: Authentication context
        trigger_service: Injected trigger service
        
    Returns:
        Paginated execution history
        
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
        
        # Get execution history
        executions = await trigger_service.get_execution_history(
            trigger_id=trigger_id,
            limit=page_size + 1,  # Get one extra to check if there's a next page
            offset=offset
        )
        
        # Check if there's a next page
        has_next = len(executions) > page_size
        if has_next:
            executions = executions[:-1]  # Remove the extra execution
        
        # Convert to response models
        execution_responses = [
            TriggerExecutionResponse.from_domain_model(execution)
            for execution in executions
        ]
        
        # For total count, we'd need a separate count query in a real implementation
        # For now, we'll use a simplified approach
        total = offset + len(execution_responses) + (1 if has_next else 0)
        
        return ExecutionHistoryResponse(
            executions=execution_responses,
            total=total,
            page=page,
            page_size=page_size,
            has_next=has_next
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get execution history for trigger {trigger_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get execution history: {str(e)}")


@router.get("/{trigger_id}/status", response_model=TriggerStatusResponse)
async def get_trigger_status(
    trigger_id: UUID,
    auth_context: A2AAuthContext = Depends(require_a2a_execute_auth),
    trigger_service: TriggerService = Depends(get_trigger_service),
) -> TriggerStatusResponse:
    """
    Get trigger status and schedule information.
    
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
        if hasattr(trigger, 'cron_expression'):
            schedule_info = await trigger_service.get_cron_schedule_info(trigger_id)
        
        return TriggerStatusResponse(
            trigger_id=trigger_id,
            is_active=trigger.is_active,
            last_execution_at=trigger.last_execution_at,
            consecutive_failures=trigger.consecutive_failures,
            should_disable_due_to_failures=trigger.should_disable_due_to_failures(),
            schedule_info=schedule_info
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get trigger status for {trigger_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get trigger status: {str(e)}")


# Health check endpoint
@router.get("/health", response_model=Dict[str, Any])
async def triggers_health_check(
    trigger_service: TriggerService = Depends(get_trigger_service),
) -> Dict[str, Any]:
    """
    Health check endpoint for trigger system.
    
    Returns:
        Dictionary with health status information
    """
    try:
        if not TRIGGERS_AVAILABLE:
            return {
                "status": "unavailable",
                "service": "triggers",
                "message": "Triggers service not available",
                "timestamp": datetime.utcnow().isoformat()
            }
        
        # Try to list triggers to check if service is working
        await trigger_service.list_triggers(limit=1)
        
        return {
            "status": "healthy",
            "service": "triggers",
            "message": "Triggers service is operational",
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Triggers health check failed: {e}")
        return {
            "status": "unhealthy",
            "service": "triggers",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }