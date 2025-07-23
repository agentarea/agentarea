"""Webhook manager for handling webhook triggers."""

import json
import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from agentarea_common.events.broker import EventBroker

from .domain.enums import WebhookType, ExecutionStatus
from .domain.models import WebhookTrigger, TriggerExecution

logger = logging.getLogger(__name__)


class WebhookRequestData:
    """Data structure for webhook requests."""
    
    def __init__(
        self,
        webhook_id: str,
        method: str,
        headers: Dict[str, str],
        body: Any,
        query_params: Dict[str, str],
        received_at: Optional[datetime] = None
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
        self,
        is_valid: bool,
        parsed_data: Dict[str, Any],
        error_message: Optional[str] = None
    ):
        self.is_valid = is_valid
        self.parsed_data = parsed_data
        self.error_message = error_message


class WebhookExecutionCallback(ABC):
    """Callback interface for webhook execution."""

    @abstractmethod
    async def execute_webhook_trigger(
        self, 
        webhook_id: str, 
        request_data: Dict[str, Any]
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
        headers: Dict[str, str],
        body: Any,
        query_params: Dict[str, str]
    ) -> Dict[str, Any]:
        """
        Process incoming webhook request:
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
        self, 
        trigger: WebhookTrigger, 
        headers: Dict[str, str], 
        body: Any
    ) -> bool:
        """Apply trigger-specific validation rules to webhook request."""
        pass

    @abstractmethod
    async def apply_rate_limiting(self, webhook_id: str) -> bool:
        """Apply rate limiting to webhook requests."""
        pass

    @abstractmethod
    async def get_webhook_response(
        self, 
        success: bool, 
        error_message: Optional[str] = None
    ) -> Dict[str, Any]:
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
        event_broker: Optional[EventBroker] = None,
        base_url: str = "/webhooks"
    ):
        self.execution_callback = execution_callback
        self.event_broker = event_broker
        self.base_url = base_url.rstrip('/')
        self._registered_webhooks: Dict[str, WebhookTrigger] = {}
        self._rate_limit_cache: Dict[str, list] = {}  # webhook_id -> list of timestamps

    def generate_webhook_url(self, trigger_id: UUID) -> str:
        """Generate unique webhook URL for trigger."""
        # Use trigger ID as webhook ID for simplicity
        webhook_id = str(trigger_id).replace('-', '')[:16]  # Shorter ID
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
        headers: Dict[str, str],
        body: Any,
        query_params: Dict[str, str]
    ) -> Dict[str, Any]:
        """Process incoming webhook request."""
        start_time = time.time()
        
        try:
            # Find the trigger
            trigger = self._registered_webhooks.get(webhook_id)
            if not trigger:
                logger.warning(f"Webhook {webhook_id} not found")
                return await self.get_webhook_response(
                    False, 
                    f"Webhook {webhook_id} not found"
                )

            # Check if trigger is active
            if not trigger.is_active:
                logger.warning(f"Webhook {webhook_id} is inactive")
                return await self.get_webhook_response(
                    False, 
                    "Webhook is inactive"
                )

            # Validate HTTP method
            if not await self.validate_webhook_method(trigger, method):
                logger.warning(f"Method {method} not allowed for webhook {webhook_id}")
                return await self.get_webhook_response(
                    False, 
                    f"Method {method} not allowed"
                )

            # Apply rate limiting
            if not await self.apply_rate_limiting(webhook_id):
                logger.warning(f"Rate limit exceeded for webhook {webhook_id}")
                return await self.get_webhook_response(
                    False, 
                    "Rate limit exceeded"
                )

            # Apply validation rules
            if not await self.apply_validation_rules(trigger, headers, body):
                logger.warning(f"Validation failed for webhook {webhook_id}")
                return await self.get_webhook_response(
                    False, 
                    "Request validation failed"
                )

            # Create request data
            request_data = WebhookRequestData(
                webhook_id=webhook_id,
                method=method,
                headers=headers,
                body=body,
                query_params=query_params
            )

            # Parse webhook data based on type
            parsed_data = await self._parse_webhook_data(trigger, request_data)

            # Execute the webhook trigger
            execution = await self.execution_callback.execute_webhook_trigger(
                webhook_id, 
                parsed_data
            )

            # Log execution time
            execution_time_ms = int((time.time() - start_time) * 1000)
            logger.info(
                f"Webhook {webhook_id} processed in {execution_time_ms}ms, "
                f"status: {execution.status}"
            )

            # Return success response
            return await self.get_webhook_response(True)

        except Exception as e:
            execution_time_ms = int((time.time() - start_time) * 1000)
            logger.error(
                f"Error processing webhook {webhook_id} in {execution_time_ms}ms: {e}"
            )
            return await self.get_webhook_response(False, str(e))

    async def validate_webhook_method(self, trigger: WebhookTrigger, method: str) -> bool:
        """Validate HTTP method against trigger's allowed methods."""
        return method.upper() in [m.upper() for m in trigger.allowed_methods]

    async def apply_validation_rules(
        self, 
        trigger: WebhookTrigger, 
        headers: Dict[str, str], 
        body: Any
    ) -> bool:
        """Apply trigger-specific validation rules to webhook request."""
        if not trigger.validation_rules:
            return True

        try:
            # Check required headers
            required_headers = trigger.validation_rules.get('required_headers', [])
            for header in required_headers:
                if header.lower() not in [h.lower() for h in headers.keys()]:
                    logger.warning(f"Required header {header} missing")
                    return False

            # Check content type if specified
            expected_content_type = trigger.validation_rules.get('content_type')
            if expected_content_type:
                actual_content_type = headers.get('content-type', '').lower()
                if expected_content_type.lower() not in actual_content_type:
                    logger.warning(
                        f"Content type mismatch: expected {expected_content_type}, "
                        f"got {actual_content_type}"
                    )
                    return False

            # Check body format if specified
            body_format = trigger.validation_rules.get('body_format')
            if body_format == 'json' and body is not None:
                if not isinstance(body, dict):
                    try:
                        json.loads(str(body))
                    except (json.JSONDecodeError, TypeError):
                        logger.warning("Expected JSON body but got invalid JSON")
                        return False

            return True

        except Exception as e:
            logger.error(f"Error applying validation rules: {e}")
            return False

    async def apply_rate_limiting(self, webhook_id: str) -> bool:
        """Apply rate limiting to webhook requests."""
        current_time = time.time()
        window_seconds = 60  # 1 minute window
        max_requests = 60    # Max 60 requests per minute per webhook

        # Get or create rate limit cache for this webhook
        if webhook_id not in self._rate_limit_cache:
            self._rate_limit_cache[webhook_id] = []

        timestamps = self._rate_limit_cache[webhook_id]

        # Remove old timestamps outside the window
        timestamps[:] = [ts for ts in timestamps if current_time - ts < window_seconds]

        # Check if we're over the limit
        if len(timestamps) >= max_requests:
            return False

        # Add current timestamp
        timestamps.append(current_time)
        return True

    async def get_webhook_response(
        self, 
        success: bool, 
        error_message: Optional[str] = None
    ) -> Dict[str, Any]:
        """Generate appropriate HTTP response for webhook requests."""
        if success:
            return {
                "status_code": 200,
                "body": {
                    "status": "success",
                    "message": "Webhook processed successfully"
                }
            }
        else:
            return {
                "status_code": 400,
                "body": {
                    "status": "error",
                    "message": error_message or "Webhook processing failed"
                }
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
        self, 
        trigger: WebhookTrigger, 
        request_data: WebhookRequestData
    ) -> Dict[str, Any]:
        """Parse webhook data based on webhook type."""
        base_data = {
            "webhook_id": request_data.webhook_id,
            "method": request_data.method,
            "headers": request_data.headers,
            "query_params": request_data.query_params,
            "received_at": request_data.received_at.isoformat(),
            "webhook_type": trigger.webhook_type.value
        }

        # Parse body based on webhook type
        if trigger.webhook_type == WebhookType.TELEGRAM:
            return await self._parse_telegram_webhook(request_data, base_data)
        elif trigger.webhook_type == WebhookType.SLACK:
            return await self._parse_slack_webhook(request_data, base_data)
        elif trigger.webhook_type == WebhookType.GITHUB:
            return await self._parse_github_webhook(request_data, base_data)
        else:
            # Generic webhook - just include raw body
            return {
                **base_data,
                "body": request_data.body,
                "raw_data": request_data.body
            }

    async def _parse_telegram_webhook(
        self, 
        request_data: WebhookRequestData, 
        base_data: Dict[str, Any]
    ) -> Dict[str, Any]:
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
                "raw_data": telegram_data
            }

            # Extract message data if present
            if "message" in telegram_data:
                message = telegram_data["message"]
                parsed_data.update({
                    "chat_id": message.get("chat", {}).get("id"),
                    "user_id": message.get("from", {}).get("id"),
                    "username": message.get("from", {}).get("username"),
                    "text": message.get("text"),
                    "message_id": message.get("message_id"),
                    "date": message.get("date")
                })

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
            return {
                **base_data,
                "body": request_data.body,
                "parse_error": str(e)
            }

    async def _parse_slack_webhook(
        self, 
        request_data: WebhookRequestData, 
        base_data: Dict[str, Any]
    ) -> Dict[str, Any]:
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
                "raw_data": slack_data
            }

            return parsed_data

        except Exception as e:
            logger.error(f"Error parsing Slack webhook: {e}")
            return {
                **base_data,
                "body": request_data.body,
                "parse_error": str(e)
            }

    async def _parse_github_webhook(
        self, 
        request_data: WebhookRequestData, 
        base_data: Dict[str, Any]
    ) -> Dict[str, Any]:
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
                "raw_data": github_data
            }

            return parsed_data

        except Exception as e:
            logger.error(f"Error parsing GitHub webhook: {e}")
            return {
                **base_data,
                "body": request_data.body,
                "parse_error": str(e)
            }