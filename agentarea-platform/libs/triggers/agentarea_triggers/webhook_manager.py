"""Webhook manager for handling webhook triggers."""

import json
import time
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml
from agentarea_common.events.broker import EventBroker

from .domain.enums import WebhookType
from .domain.models import TriggerExecution, WebhookTrigger
from .logging_utils import (
    TriggerLogger,
    WebhookValidationError,
    generate_correlation_id,
    set_correlation_id,
)

logger = TriggerLogger(__name__)


class WebhookRequestData:
    """Data structure for webhook requests."""

    def __init__(
        self,
        webhook_id: str,
        method: str,
        headers: dict[str, str],
        body: Any,
        query_params: dict[str, str],
        received_at: datetime | None = None,
    ):
        self.webhook_id = webhook_id
        self.method = method.upper()
        self.headers = headers
        self.body = body
        self.query_params = query_params
        self.received_at = received_at or datetime.utcnow()


class WebhookValidationResult:
    """Result of webhook validation."""

    def __init__(
        self, is_valid: bool, parsed_data: dict[str, Any], error_message: str | None = None
    ):
        self.is_valid = is_valid
        self.parsed_data = parsed_data
        self.error_message = error_message


class WebhookExecutionCallback(ABC):
    """Callback interface for webhook execution."""

    @abstractmethod
    async def execute_webhook_trigger(
        self, webhook_id: str, request_data: dict[str, Any]
    ) -> TriggerExecution:
        """Called when a webhook trigger should be executed."""
        pass


class WebhookManager(ABC):
    """Abstract interface for webhook management implementations."""

    @abstractmethod
    def generate_webhook_url(self, trigger_id: UUID) -> str:
        """Generate unique webhook URL like /webhooks/abc123 for trigger."""
        pass

    @abstractmethod
    async def register_webhook(self, trigger: WebhookTrigger) -> None:
        """Register webhook trigger for incoming requests."""
        pass

    @abstractmethod
    async def unregister_webhook(self, webhook_id: str) -> None:
        """Unregister webhook trigger."""
        pass

    @abstractmethod
    async def handle_webhook_request(
        self,
        webhook_id: str,
        method: str,
        headers: dict[str, str],
        body: Any,
        query_params: dict[str, str],
    ) -> dict[str, Any]:
        """Process incoming webhook request:
        1. Find trigger by webhook_id
        2. Parse request data (Telegram, Slack, GitHub, etc.)
        3. Call TriggerService to evaluate and execute
        4. Return HTTP response (200 OK, 400 Bad Request, etc.)
        """
        pass

    @abstractmethod
    async def validate_webhook_method(self, trigger: WebhookTrigger, method: str) -> bool:
        """Validate HTTP method against trigger's allowed methods."""
        pass

    @abstractmethod
    async def apply_validation_rules(
        self, trigger: WebhookTrigger, headers: dict[str, str], body: Any
    ) -> bool:
        """Apply trigger-specific validation rules to webhook request."""
        pass

    @abstractmethod
    async def apply_rate_limiting(self, webhook_id: str) -> bool:
        """Apply rate limiting to webhook requests."""
        pass

    @abstractmethod
    async def get_webhook_response(
        self, success: bool, error_message: str | None = None
    ) -> dict[str, Any]:
        """Generate appropriate HTTP response for webhook requests."""
        pass

    @abstractmethod
    async def is_healthy(self) -> bool:
        """Check if the webhook manager is healthy and operational."""
        pass


class DefaultWebhookManager(WebhookManager):
    """Default implementation of WebhookManager."""

    def __init__(
        self,
        execution_callback: WebhookExecutionCallback,
        event_broker: EventBroker | None = None,
        base_url: str = "/webhooks",
    ):
        self.execution_callback = execution_callback
        self.event_broker = event_broker
        self.base_url = base_url.rstrip("/")
        self._registered_webhooks: dict[str, WebhookTrigger] = {}
        self._load_provider_config()

    def _load_provider_config(self):
        """Load webhook provider configuration."""
        try:
            config_path = Path(__file__).parent / "config" / "webhook_providers.yaml"
            if config_path.exists():
                with open(config_path) as f:
                    config = yaml.safe_load(f)
                    self.providers = {p["type"]: p for p in config.get("providers", [])}
                    logger.info(f"Loaded {len(self.providers)} webhook providers from config")
            else:
                logger.warning(f"Webhook provider config not found at {config_path}")
                self.providers = {}
        except Exception as e:
            logger.error(f"Failed to load webhook provider config: {e}")
            self.providers = {}

    def _extract_value_by_path(self, data: Any, path: str) -> Any:
        """Extract value from nested dict using dot notation."""
        if not path:
            return None

        parts = path.split(".")
        current = data

        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list):
                # Simple list index support e.g. items.0.id
                try:
                    idx = int(part)
                    if 0 <= idx < len(current):
                        current = current[idx]
                    else:
                        return None
                except ValueError:
                    return None
            else:
                return None

            if current is None:
                return None

        return current

    def generate_webhook_url(self, trigger_id: UUID) -> str:
        """Generate unique webhook URL for trigger."""
        # Use trigger ID as webhook ID for simplicity
        webhook_id = str(trigger_id).replace("-", "")[:16]  # Shorter ID
        return f"{self.base_url}/{webhook_id}"

    async def register_webhook(self, trigger: WebhookTrigger) -> None:
        """Register webhook trigger for incoming requests."""
        self._registered_webhooks[trigger.webhook_id] = trigger
        logger.info(f"Registered webhook {trigger.webhook_id} for trigger {trigger.id}")

    async def unregister_webhook(self, webhook_id: str) -> None:
        """Unregister webhook trigger."""
        if webhook_id in self._registered_webhooks:
            del self._registered_webhooks[webhook_id]
            logger.info(f"Unregistered webhook {webhook_id}")

    async def handle_webhook_request(
        self,
        webhook_id: str,
        method: str,
        headers: dict[str, str],
        body: Any,
        query_params: dict[str, str],
    ) -> dict[str, Any]:
        """Process incoming webhook request."""
        correlation_id = generate_correlation_id()
        set_correlation_id(correlation_id)
        start_time = time.time()

        try:
            logger.info(
                "Processing webhook request",
                webhook_id=webhook_id,
                method=method,
                content_type=headers.get("content-type", "unknown"),
            )

            # Find the trigger
            trigger = self._registered_webhooks.get(webhook_id)
            if not trigger:
                error_msg = f"Webhook {webhook_id} not found"
                logger.warning(error_msg, webhook_id=webhook_id)
                return await self.get_webhook_response(False, error_msg)

            # Check if trigger is active
            if not trigger.is_active:
                error_msg = f"Webhook {webhook_id} is inactive"
                logger.warning(error_msg, webhook_id=webhook_id, trigger_id=trigger.id)
                return await self.get_webhook_response(False, "Webhook is inactive")

            # Validate HTTP method
            if not await self.validate_webhook_method(trigger, method):
                error_msg = f"Method {method} not allowed for webhook {webhook_id}"
                logger.warning(
                    error_msg,
                    webhook_id=webhook_id,
                    trigger_id=trigger.id,
                    method=method,
                    allowed_methods=trigger.allowed_methods,
                )
                return await self.get_webhook_response(False, f"Method {method} not allowed")

            # Apply validation rules
            try:
                validation_result = await self.apply_validation_rules(trigger, headers, body)
                if not validation_result:
                    error_msg = "Request validation failed"
                    logger.warning(
                        error_msg,
                        webhook_id=webhook_id,
                        trigger_id=trigger.id,
                        content_type=headers.get("content-type"),
                    )
                    return await self.get_webhook_response(False, "Request validation failed")
            except Exception as validation_error:
                error_msg = f"Validation error: {validation_error}"
                logger.error(error_msg, webhook_id=webhook_id, trigger_id=trigger.id)
                return await self.get_webhook_response(False, "Request validation failed")

            # Create request data
            request_data = WebhookRequestData(
                webhook_id=webhook_id,
                method=method,
                headers=headers,
                body=body,
                query_params=query_params,
            )

            # Parse webhook data based on type
            try:
                parsed_data = await self._parse_webhook_data(trigger, request_data)
                logger.debug(
                    "Successfully parsed webhook data",
                    webhook_id=webhook_id,
                    trigger_id=trigger.id,
                    webhook_type=trigger.webhook_type.value,
                )
            except Exception as parse_error:
                error_msg = f"Failed to parse webhook data: {parse_error}"
                logger.error(
                    error_msg,
                    webhook_id=webhook_id,
                    trigger_id=trigger.id,
                    webhook_type=trigger.webhook_type.value,
                )
                return await self.get_webhook_response(False, "Failed to parse request data")

            # Execute the webhook trigger
            try:
                execution = await self.execution_callback.execute_webhook_trigger(
                    webhook_id, parsed_data
                )

                execution_time_ms = int((time.time() - start_time) * 1000)
                logger.info(
                    "Webhook processed successfully",
                    webhook_id=webhook_id,
                    trigger_id=trigger.id,
                    execution_time_ms=execution_time_ms,
                    status=execution.status.value if hasattr(execution, "status") else "unknown",
                )

                # Return success response
                return await self.get_webhook_response(True)

            except Exception as execution_error:
                execution_time_ms = int((time.time() - start_time) * 1000)
                error_msg = f"Webhook execution failed: {execution_error}"
                logger.error(
                    error_msg,
                    webhook_id=webhook_id,
                    trigger_id=trigger.id,
                    execution_time_ms=execution_time_ms,
                )
                return await self.get_webhook_response(False, "Webhook execution failed")

        except Exception as e:
            execution_time_ms = int((time.time() - start_time) * 1000)
            error_msg = f"Unexpected error processing webhook: {e}"
            logger.error(error_msg, webhook_id=webhook_id, execution_time_ms=execution_time_ms)
            return await self.get_webhook_response(False, "Internal server error")

    async def validate_webhook_method(self, trigger: WebhookTrigger, method: str) -> bool:
        """Validate HTTP method against trigger's allowed methods."""
        return method.upper() in [m.upper() for m in trigger.allowed_methods]

    async def apply_validation_rules(
        self, trigger: WebhookTrigger, headers: dict[str, str], body: Any
    ) -> bool:
        """Apply trigger-specific validation rules to webhook request."""
        if not trigger.validation_rules:
            logger.debug(
                "No validation rules defined, allowing request",
                webhook_id=trigger.webhook_id,
                trigger_id=trigger.id,
            )
            return True

        try:
            logger.debug(
                "Applying validation rules",
                webhook_id=trigger.webhook_id,
                trigger_id=trigger.id,
                rules_count=len(trigger.validation_rules),
            )

            # Check required headers
            required_headers = trigger.validation_rules.get("required_headers", [])
            for header in required_headers:
                if header.lower() not in [h.lower() for h in headers.keys()]:
                    logger.warning(
                        f"Required header missing: {header}",
                        webhook_id=trigger.webhook_id,
                        trigger_id=trigger.id,
                        required_header=header,
                        available_headers=list(headers.keys()),
                    )
                    return False

            # Check content type if specified
            expected_content_type = trigger.validation_rules.get("content_type")
            if expected_content_type:
                actual_content_type = headers.get("content-type", "").lower()
                if expected_content_type.lower() not in actual_content_type:
                    logger.warning(
                        "Content type mismatch",
                        webhook_id=trigger.webhook_id,
                        trigger_id=trigger.id,
                        expected_content_type=expected_content_type,
                        actual_content_type=actual_content_type,
                    )
                    return False

            # Check body format if specified
            body_format = trigger.validation_rules.get("body_format")
            if body_format == "json" and body is not None:
                if not isinstance(body, dict):
                    try:
                        json.loads(str(body))
                        logger.debug(
                            "Successfully validated JSON body format",
                            webhook_id=trigger.webhook_id,
                            trigger_id=trigger.id,
                        )
                    except (json.JSONDecodeError, TypeError) as json_error:
                        logger.warning(
                            f"Expected JSON body but got invalid JSON: {json_error}",
                            webhook_id=trigger.webhook_id,
                            trigger_id=trigger.id,
                            body_type=type(body).__name__,
                        )
                        return False

            logger.debug(
                "All validation rules passed", webhook_id=trigger.webhook_id, trigger_id=trigger.id
            )
            return True

        except Exception as e:
            logger.error(
                f"Error applying validation rules: {e}",
                webhook_id=trigger.webhook_id,
                trigger_id=trigger.id,
            )
            raise WebhookValidationError(
                f"Validation rule processing failed: {e}",
                webhook_id=trigger.webhook_id,
                trigger_id=str(trigger.id),
                original_error=str(e),
            ) from e

    async def apply_rate_limiting(self, webhook_id: str) -> bool:
        """Rate limiting is handled at infrastructure layer.

        This method is kept for interface compatibility but always returns True
        since rate limiting is now handled by ingress/load balancer/API gateway.

        Args:
            webhook_id: The webhook ID (unused)

        Returns:
            Always True - rate limiting handled at infrastructure layer
        """
        # Rate limiting moved to infrastructure layer (ingress/load balancer/API gateway)
        # This provides better performance and prevents application-level bottlenecks
        return True

    async def get_webhook_response(
        self, success: bool, error_message: str | None = None
    ) -> dict[str, Any]:
        """Generate appropriate HTTP response for webhook requests."""
        if success:
            return {
                "status_code": 200,
                "body": {"status": "success", "message": "Webhook processed successfully"},
            }
        else:
            return {
                "status_code": 400,
                "body": {
                    "status": "error",
                    "message": error_message or "Webhook processing failed",
                },
            }

    async def is_healthy(self) -> bool:
        """Check if the webhook manager is healthy and operational."""
        try:
            # Basic health check - could be extended with more sophisticated checks
            return True
        except Exception as e:
            logger.error(f"Webhook manager health check failed: {e}")
            return False

    async def _parse_webhook_data(
        self, trigger: WebhookTrigger, request_data: WebhookRequestData
    ) -> dict[str, Any]:
        """Parse webhook data based on webhook type."""
        base_data = {
            "webhook_id": request_data.webhook_id,
            "method": request_data.method,
            "headers": request_data.headers,
            "query_params": request_data.query_params,
            "received_at": request_data.received_at.isoformat(),
            "webhook_type": trigger.webhook_type,
        }

        webhook_type = trigger.webhook_type
        # Handle enum value if needed (though model is str now)
        if hasattr(webhook_type, "value"):
            webhook_type = webhook_type.value

        # Check provider config first
        provider = self.providers.get(webhook_type)
        if provider:
            parser_config = provider.get("parser", {})
            strategy = parser_config.get("strategy")

            if strategy == "code":
                # Fallback to specific methods
                # We map known types to their legacy method names
                method_map = {
                    "telegram": "_parse_telegram_webhook",
                    "slack": "_parse_slack_webhook",
                    "github": "_parse_github_webhook",
                    "discord": "_parse_discord_webhook",
                    "linear": "_parse_linear_webhook",
                }
                method_name = method_map.get(webhook_type)
                if method_name and hasattr(self, method_name):
                    return await getattr(self, method_name)(request_data, base_data)

            elif strategy == "mapping":
                mapping = parser_config.get("mapping", {})
                return await self._parse_generic_mapping_webhook(request_data, base_data, mapping)

        # Fallback for backward compatibility or hardcoded types not in config
        if webhook_type == WebhookType.TELEGRAM:
            return await self._parse_telegram_webhook(request_data, base_data)
        elif webhook_type == WebhookType.SLACK:
            return await self._parse_slack_webhook(request_data, base_data)
        elif webhook_type == WebhookType.GITHUB:
            return await self._parse_github_webhook(request_data, base_data)
        elif webhook_type == WebhookType.DISCORD:
            return await self._parse_discord_webhook(request_data, base_data)
        elif webhook_type == WebhookType.LINEAR:
            return await self._parse_linear_webhook(request_data, base_data)
        else:
            # Generic webhook - just include raw body
            return {**base_data, "body": request_data.body, "raw_data": request_data.body}

    async def _parse_generic_mapping_webhook(
        self, request_data: WebhookRequestData, base_data: dict[str, Any], mapping: dict[str, str]
    ) -> dict[str, Any]:
        """Parse webhook data using generic mapping."""
        try:
            # Parse body if it's a string
            if isinstance(request_data.body, dict):
                body_data = request_data.body
            elif isinstance(request_data.body, str):
                try:
                    body_data = json.loads(request_data.body)
                except json.JSONDecodeError:
                    body_data = {}
            else:
                body_data = {}

            parsed_data = base_data.copy()

            for target_field, source_path in mapping.items():
                parsed_data[target_field] = self._extract_value_by_path(body_data, source_path)

            parsed_data["raw_data"] = body_data
            return parsed_data

        except Exception as e:
            logger.error(f"Error parsing mapped webhook: {e}")
            return {**base_data, "body": request_data.body, "parse_error": str(e)}

    async def _parse_telegram_webhook(
        self, request_data: WebhookRequestData, base_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Parse Telegram webhook data."""
        try:
            # Telegram sends JSON data
            if isinstance(request_data.body, dict):
                telegram_data = request_data.body
            else:
                telegram_data = json.loads(request_data.body)

            # Extract common Telegram fields
            parsed_data = {
                **base_data,
                "telegram_update_id": telegram_data.get("update_id"),
                "raw_data": telegram_data,
            }

            # Extract message data if present
            if "message" in telegram_data:
                message = telegram_data["message"]
                parsed_data.update(
                    {
                        "chat_id": message.get("chat", {}).get("id"),
                        "user_id": message.get("from", {}).get("id"),
                        "username": message.get("from", {}).get("username"),
                        "text": message.get("text"),
                        "message_id": message.get("message_id"),
                        "date": message.get("date"),
                    }
                )

                # Check for document/file
                if "document" in message:
                    parsed_data["document"] = message["document"]
                    parsed_data["has_file"] = True

                # Check for photo
                if "photo" in message:
                    parsed_data["photo"] = message["photo"]
                    parsed_data["has_photo"] = True

            return parsed_data

        except Exception as e:
            logger.error(f"Error parsing Telegram webhook: {e}")
            return {**base_data, "body": request_data.body, "parse_error": str(e)}

    async def _parse_slack_webhook(
        self, request_data: WebhookRequestData, base_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Parse Slack webhook data."""
        try:
            # Slack can send JSON or form data
            if isinstance(request_data.body, dict):
                slack_data = request_data.body
            else:
                try:
                    slack_data = json.loads(request_data.body)
                except json.JSONDecodeError:
                    # Might be form data
                    slack_data = {"raw_body": request_data.body}

            parsed_data = {
                **base_data,
                "slack_team_id": slack_data.get("team_id"),
                "slack_channel_id": slack_data.get("channel_id"),
                "slack_user_id": slack_data.get("user_id"),
                "slack_text": slack_data.get("text"),
                "slack_timestamp": slack_data.get("ts"),
                "raw_data": slack_data,
            }

            return parsed_data

        except Exception as e:
            logger.error(f"Error parsing Slack webhook: {e}")
            return {**base_data, "body": request_data.body, "parse_error": str(e)}

    async def _parse_github_webhook(
        self, request_data: WebhookRequestData, base_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Parse GitHub webhook data."""
        try:
            # GitHub sends JSON data
            if isinstance(request_data.body, dict):
                github_data = request_data.body
            else:
                github_data = json.loads(request_data.body)

            # Extract GitHub event type from headers
            event_type = request_data.headers.get("x-github-event", "unknown")

            parsed_data = {
                **base_data,
                "github_event": event_type,
                "github_delivery": request_data.headers.get("x-github-delivery"),
                "repository": github_data.get("repository", {}).get("full_name"),
                "sender": github_data.get("sender", {}).get("login"),
                "action": github_data.get("action"),
                "raw_data": github_data,
            }

            return parsed_data

        except Exception as e:
            logger.error(f"Error parsing GitHub webhook: {e}")
            return {**base_data, "body": request_data.body, "parse_error": str(e)}

    async def _parse_discord_webhook(
        self, request_data: WebhookRequestData, base_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Parse Discord webhook data."""
        try:
            if isinstance(request_data.body, dict):
                discord_data = request_data.body
            else:
                discord_data = json.loads(request_data.body)

            parsed_data = {
                **base_data,
                "discord_channel_id": discord_data.get("channel_id"),
                "discord_guild_id": discord_data.get("guild_id"),
                "discord_author": discord_data.get("author", {}).get("username"),
                "discord_content": discord_data.get("content"),
                "raw_data": discord_data,
            }
            return parsed_data
        except Exception as e:
            logger.error(f"Error parsing Discord webhook: {e}")
            return {**base_data, "body": request_data.body, "parse_error": str(e)}

    async def _parse_linear_webhook(
        self, request_data: WebhookRequestData, base_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Parse Linear webhook data."""
        try:
            if isinstance(request_data.body, dict):
                linear_data = request_data.body
            else:
                linear_data = json.loads(request_data.body)

            parsed_data = {
                **base_data,
                "linear_action": linear_data.get("action"),
                "linear_type": linear_data.get("type"),
                "linear_created_at": linear_data.get("createdAt"),
                "linear_data": linear_data.get("data"),
                "linear_url": linear_data.get("url"),
                "raw_data": linear_data,
            }
            return parsed_data
        except Exception as e:
            logger.error(f"Error parsing Linear webhook: {e}")
            return {**base_data, "body": request_data.body, "parse_error": str(e)}
