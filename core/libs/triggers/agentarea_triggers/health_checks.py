"""Health check implementations for trigger system components."""

import logging
from datetime import datetime, timedelta
from typing import Any

from agentarea_common.config import get_settings

from .infrastructure.repository import TriggerExecutionRepository, TriggerRepository
from .temporal_schedule_manager import TemporalScheduleManager
from .webhook_manager import WebhookManager

logger = logging.getLogger(__name__)


class TriggerSystemHealthCheck:
    """Health check coordinator for trigger system components."""

    def __init__(
        self,
        trigger_repository: TriggerRepository | None = None,
        trigger_execution_repository: TriggerExecutionRepository | None = None,
        temporal_schedule_manager: TemporalScheduleManager | None = None,
        webhook_manager: WebhookManager | None = None,
    ):
        self.trigger_repository = trigger_repository
        self.trigger_execution_repository = trigger_execution_repository
        self.temporal_schedule_manager = temporal_schedule_manager
        self.webhook_manager = webhook_manager
        self.settings = get_settings().triggers

    async def check_all_components(self) -> dict[str, Any]:
        """Check health of all trigger system components.

        Returns:
            Dictionary with health status of each component
        """
        health_status = {
            "overall_status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "components": {},
        }

        # Check database connectivity
        db_health = await self._check_database_health()
        health_status["components"]["database"] = db_health

        # Check temporal schedule manager
        temporal_health = await self._check_temporal_health()
        health_status["components"]["temporal_schedules"] = temporal_health

        # Check webhook manager
        webhook_health = await self._check_webhook_health()
        health_status["components"]["webhook_manager"] = webhook_health

        # Check trigger execution metrics
        metrics_health = await self._check_execution_metrics()
        health_status["components"]["execution_metrics"] = metrics_health

        # Determine overall status
        component_statuses = [comp["status"] for comp in health_status["components"].values()]

        if any(status == "unhealthy" for status in component_statuses):
            health_status["overall_status"] = "unhealthy"
        elif any(status == "degraded" for status in component_statuses):
            health_status["overall_status"] = "degraded"

        return health_status

    async def _check_database_health(self) -> dict[str, Any]:
        """Check database connectivity and basic operations."""
        try:
            if not self.trigger_repository:
                return {
                    "status": "unknown",
                    "message": "Trigger repository not available",
                    "details": {},
                }

            # Test basic database connectivity
            start_time = datetime.utcnow()

            # Try to count triggers (lightweight operation)
            trigger_count = await self.trigger_repository.count_all()

            # Try to count recent executions
            execution_count = 0
            if self.trigger_execution_repository:
                since = datetime.utcnow() - timedelta(hours=1)
                execution_count = await self.trigger_execution_repository.count_since(since)

            response_time = (datetime.utcnow() - start_time).total_seconds() * 1000

            return {
                "status": "healthy",
                "message": "Database connectivity OK",
                "details": {
                    "trigger_count": trigger_count,
                    "recent_executions": execution_count,
                    "response_time_ms": round(response_time, 2),
                },
            }

        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return {
                "status": "unhealthy",
                "message": f"Database connectivity failed: {e!s}",
                "details": {"error": str(e)},
            }

    async def _check_temporal_health(self) -> dict[str, Any]:
        """Check Temporal schedule manager health."""
        try:
            if not self.temporal_schedule_manager:
                return {
                    "status": "unknown",
                    "message": "Temporal schedule manager not available",
                    "details": {},
                }

            # Check if temporal client is healthy
            is_healthy = await self.temporal_schedule_manager.is_healthy()

            if is_healthy:
                # Get some basic stats
                active_schedules = await self.temporal_schedule_manager.get_active_schedule_count()

                return {
                    "status": "healthy",
                    "message": "Temporal schedules operational",
                    "details": {
                        "active_schedules": active_schedules,
                        "namespace": self.settings.TEMPORAL_SCHEDULE_NAMESPACE,
                        "task_queue": self.settings.TEMPORAL_SCHEDULE_TASK_QUEUE,
                    },
                }
            else:
                return {
                    "status": "unhealthy",
                    "message": "Temporal client not responding",
                    "details": {},
                }

        except Exception as e:
            logger.error(f"Temporal health check failed: {e}")
            return {
                "status": "unhealthy",
                "message": f"Temporal health check failed: {e!s}",
                "details": {"error": str(e)},
            }

    async def _check_webhook_health(self) -> dict[str, Any]:
        """Check webhook manager health."""
        try:
            if not self.webhook_manager:
                return {
                    "status": "unknown",
                    "message": "Webhook manager not available",
                    "details": {},
                }

            # Check webhook manager health
            is_healthy = await self.webhook_manager.is_healthy()

            if is_healthy:
                return {
                    "status": "healthy",
                    "message": "Webhook manager operational",
                    "details": {
                        "base_url": self.settings.WEBHOOK_BASE_URL,
                        "rate_limit_per_minute": self.settings.WEBHOOK_RATE_LIMIT_PER_MINUTE,
                    },
                }
            else:
                return {
                    "status": "degraded",
                    "message": "Webhook manager reporting issues",
                    "details": {},
                }

        except Exception as e:
            logger.error(f"Webhook health check failed: {e}")
            return {
                "status": "unhealthy",
                "message": f"Webhook health check failed: {e!s}",
                "details": {"error": str(e)},
            }

    async def _check_execution_metrics(self) -> dict[str, Any]:
        """Check trigger execution metrics and identify potential issues."""
        try:
            if not self.trigger_execution_repository:
                return {
                    "status": "unknown",
                    "message": "Execution repository not available",
                    "details": {},
                }

            # Check recent execution patterns
            now = datetime.utcnow()
            last_hour = now - timedelta(hours=1)
            last_day = now - timedelta(days=1)

            # Get execution counts
            executions_last_hour = await self.trigger_execution_repository.count_since(last_hour)
            executions_last_day = await self.trigger_execution_repository.count_since(last_day)

            # Get failure rates
            failures_last_hour = await self.trigger_execution_repository.count_failures_since(
                last_hour
            )
            failures_last_day = await self.trigger_execution_repository.count_failures_since(
                last_day
            )

            # Calculate failure rates
            failure_rate_hour = (failures_last_hour / max(executions_last_hour, 1)) * 100
            failure_rate_day = (failures_last_day / max(executions_last_day, 1)) * 100

            # Determine status based on failure rates
            status = "healthy"
            message = "Execution metrics normal"

            if failure_rate_hour > 50:
                status = "unhealthy"
                message = f"High failure rate in last hour: {failure_rate_hour:.1f}%"
            elif failure_rate_hour > 25:
                status = "degraded"
                message = f"Elevated failure rate in last hour: {failure_rate_hour:.1f}%"

            return {
                "status": status,
                "message": message,
                "details": {
                    "executions_last_hour": executions_last_hour,
                    "executions_last_day": executions_last_day,
                    "failure_rate_hour_percent": round(failure_rate_hour, 1),
                    "failure_rate_day_percent": round(failure_rate_day, 1),
                    "failures_last_hour": failures_last_hour,
                    "failures_last_day": failures_last_day,
                },
            }

        except Exception as e:
            logger.error(f"Execution metrics health check failed: {e}")
            return {
                "status": "unhealthy",
                "message": f"Execution metrics check failed: {e!s}",
                "details": {"error": str(e)},
            }


class ComponentHealthChecker:
    """Individual component health checker."""

    @staticmethod
    async def check_database_connection(repository) -> bool:
        """Check if database connection is working."""
        try:
            await repository.count_all()
            return True
        except Exception as e:
            logger.error(f"Database connection check failed: {e}")
            return False

    @staticmethod
    async def check_temporal_connection(schedule_manager) -> bool:
        """Check if Temporal connection is working."""
        try:
            return await schedule_manager.is_healthy()
        except Exception as e:
            logger.error(f"Temporal connection check failed: {e}")
            return False

    @staticmethod
    async def check_webhook_manager(webhook_manager) -> bool:
        """Check if webhook manager is operational."""
        try:
            return await webhook_manager.is_healthy()
        except Exception as e:
            logger.error(f"Webhook manager check failed: {e}")
            return False
