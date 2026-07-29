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
from .webhook_verification import verify_webhook_signature

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


def _execution_status_value(execution: object) -> str:
    status = getattr(execution, "status", None)
    if status is None and isinstance(execution, dict):
        status = execution.get("status")
    if status is not None and hasattr(status, "value"):
        return str(status.value)
    if status is not None:
        return str(status)
    return "unknown"


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
        raw_body: bytes | None = None,
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
        trigger_service: Any = None,
    ):
        self.execution_callback = execution_callback
        self.event_broker = event_broker
        self.base_url = base_url.rstrip("/")
        self.trigger_service = trigger_service
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
        raw_body: bytes | None = None,
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

            # Find the trigger (in-memory cache first, then DB fallback)
            trigger = self._registered_webhooks.get(webhook_id)
            if not trigger and self.trigger_service:
                try:
                    db_trigger = await self.trigger_service.get_trigger_by_webhook_id(webhook_id)
                    if db_trigger:
                        trigger = db_trigger
                        # Cache for future requests
                        self._registered_webhooks[webhook_id] = trigger
                        # Update the service's workspace context to match the trigger's workspace
                        if (
                            hasattr(self.trigger_service, "trigger_repository")
                            and db_trigger.workspace_id
                        ):
                            repo = self.trigger_service.trigger_repository
                            if hasattr(repo, "user_context") and hasattr(
                                repo.user_context, "workspace_id"
                            ):
                                repo.user_context.workspace_id = db_trigger.workspace_id
                                repo.user_context.user_id = (
                                    db_trigger.created_by or repo.user_context.user_id
                                )
                        logger.info(f"Loaded trigger from DB for webhook {webhook_id}")
                except Exception as db_err:
                    logger.warning(f"DB lookup failed for webhook {webhook_id}: {db_err}")
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

            # Verify cryptographic signature when a signing secret is configured.
            # None => not enabled (proceed); False => configured but invalid (reject).
            signature_result = verify_webhook_signature(
                trigger.webhook_type,
                trigger.validation_rules,
                trigger.webhook_config,
                headers,
                raw_body,
            )
            if signature_result is False:
                logger.warning(
                    "Webhook signature verification failed",
                    webhook_id=webhook_id,
                    trigger_id=trigger.id,
                    webhook_type=trigger.webhook_type,
                )
                return await self.get_webhook_response(False, "Signature verification failed")

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
                    webhook_type=trigger.webhook_type,
                )
            except Exception as parse_error:
                error_msg = f"Failed to parse webhook data: {parse_error}"
                logger.error(
                    error_msg,
                    webhook_id=webhook_id,
                    trigger_id=trigger.id,
                    webhook_type=trigger.webhook_type,
                )
                return await self.get_webhook_response(False, "Failed to parse request data")

            # Handle channel verification responses (Slack challenge, Discord PING)
            if parsed_data.get("_challenge_response"):
                return {
                    "status_code": 200,
                    "body": {"challenge": parsed_data.get("challenge")},
                }
            if parsed_data.get("_ping_response"):
                return {
                    "status_code": 200,
                    "body": {"type": 1},
                }

            # Extract event type from parsed data and check against trigger filter
            event_type = self._extract_event_type(trigger, parsed_data)
            if event_type:
                parsed_data["event_type"] = event_type

            # Check event type filter
            if trigger.event_types and event_type:
                if not self._matches_event_filter(event_type, trigger.event_types):
                    logger.info(
                        "Event filtered out by trigger event_types",
                        webhook_id=webhook_id,
                        event_type=event_type,
                        allowed_events=trigger.event_types,
                    )
                    return await self.get_webhook_response(True)  # 200 but don't execute

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
                    status=_execution_status_value(execution),
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

    def _extract_event_type(
        self, trigger: WebhookTrigger, parsed_data: dict[str, Any]
    ) -> str | None:
        """Extract the event type from parsed webhook data based on channel."""
        webhook_type = trigger.webhook_type

        if webhook_type == "slack":
            # Slack Events API: event.type field
            event = parsed_data.get("raw_data", {}).get("event", {})
            return event.get("type") if event else parsed_data.get("raw_data", {}).get("type")
        elif webhook_type == "github":
            # GitHub: X-GitHub-Event header + action
            event = parsed_data.get("github_event", "")
            action = parsed_data.get("action")
            return f"{event}.{action}" if action else event
        elif webhook_type == "discord":
            return parsed_data.get("raw_data", {}).get("t")
        elif webhook_type == "telegram":
            # Telegram: determine by which field is present
            raw = parsed_data.get("raw_data", {})
            for key in [
                "message",
                "edited_message",
                "channel_post",
                "callback_query",
                "inline_query",
            ]:
                if key in raw:
                    return key
            return None
        elif webhook_type == "linear":
            return parsed_data.get("raw_data", {}).get("type")
        elif webhook_type == "stripe":
            return parsed_data.get("raw_data", {}).get("type")
        elif webhook_type == "gmail":
            return "message_received"  # Gmail push notifications are always about new messages
        elif webhook_type == "teams":
            return parsed_data.get("raw_data", {}).get("type")
        return None

    def _matches_event_filter(self, event_type: str, allowed_events: list[str]) -> bool:
        """Check if event_type matches any of the allowed events.

        Supports exact match and parent match (e.g., 'pull_request' matches 'pull_request.opened').
        """
        if not allowed_events:
            return True
        for allowed in allowed_events:
            if event_type == allowed:
                return True
            # Check parent match: if allowed is "pull_request", it matches "pull_request.opened"
            if event_type.startswith(f"{allowed}."):
                return True
            # Check child match: if allowed is "pull_request.opened", and event is "pull_request.opened"
            if allowed.startswith(f"{event_type}."):
                return True
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

        # Check provider config first
        provider = self.providers.get(webhook_type)
        if provider:
            parser_config = provider.get("parser", {})
            strategy = parser_config.get("strategy")

            if strategy == "code":
                method_map = {
                    "telegram": "_parse_telegram_webhook",
                    "slack": "_parse_slack_webhook",
                    "github": "_parse_github_webhook",
                    "discord": "_parse_discord_webhook",
                    "linear": "_parse_linear_webhook",
                    "gmail": "_parse_gmail_webhook",
                    "teams": "_parse_teams_webhook",
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
        elif webhook_type == WebhookType.GMAIL:
            return await self._parse_gmail_webhook(request_data, base_data)
        elif webhook_type == WebhookType.TEAMS:
            return await self._parse_teams_webhook(request_data, base_data)
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
            message = telegram_data.get("message") or telegram_data.get("edited_message")
            if message:
                parsed_data.update(
                    {
                        "chat_id": message.get("chat", {}).get("id"),
                        "chat_type": message.get("chat", {}).get("type"),
                        "user_id": message.get("from", {}).get("id"),
                        "username": message.get("from", {}).get("username"),
                        "first_name": message.get("from", {}).get("first_name"),
                        "text": message.get("text") or message.get("caption"),
                        "message_id": message.get("message_id"),
                        "date": message.get("date"),
                    }
                )

                # Thread/reply context
                if "reply_to_message" in message:
                    reply = message["reply_to_message"]
                    parsed_data["reply_to_message_id"] = reply.get("message_id")
                    parsed_data["reply_to_text"] = reply.get("text") or reply.get("caption")

                # Media — extract file_id for any attachment type
                for media_type in (
                    "document",
                    "photo",
                    "video",
                    "voice",
                    "audio",
                    "sticker",
                    "video_note",
                    "animation",
                ):
                    if media_type in message:
                        media = message[media_type]
                        # photo is a list of sizes, take the largest
                        if media_type == "photo":
                            media = media[-1] if media else {}
                        parsed_data["media_type"] = media_type
                        parsed_data["file_id"] = media.get("file_id")
                        parsed_data["file_name"] = media.get("file_name")
                        parsed_data["mime_type"] = media.get("mime_type")
                        parsed_data[media_type] = message[media_type]
                        break

                # Location
                if "location" in message:
                    loc = message["location"]
                    parsed_data["location"] = {
                        "lat": loc.get("latitude"),
                        "lon": loc.get("longitude"),
                    }

                # Forward info
                if "forward_from" in message:
                    parsed_data["forwarded_from"] = message["forward_from"].get("username")

            # Callback query (inline button press)
            elif "callback_query" in telegram_data:
                cb = telegram_data["callback_query"]
                parsed_data.update(
                    {
                        "chat_id": cb.get("message", {}).get("chat", {}).get("id"),
                        "user_id": cb.get("from", {}).get("id"),
                        "username": cb.get("from", {}).get("username"),
                        "callback_data": cb.get("data"),
                        "message_id": cb.get("message", {}).get("message_id"),
                    }
                )

            return parsed_data

        except Exception as e:
            logger.error(f"Error parsing Telegram webhook: {e}")
            return {**base_data, "body": request_data.body, "parse_error": str(e)}

    async def _parse_slack_webhook(
        self, request_data: WebhookRequestData, base_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Parse Slack webhook data with full event support."""
        try:
            if isinstance(request_data.body, dict):
                slack_data = request_data.body
            else:
                try:
                    slack_data = json.loads(request_data.body)
                except json.JSONDecodeError:
                    slack_data = {"raw_body": request_data.body}

            # Handle Slack URL verification challenge
            if slack_data.get("type") == "url_verification":
                return {
                    **base_data,
                    "_challenge_response": True,
                    "challenge": slack_data.get("challenge"),
                    "raw_data": slack_data,
                }

            parsed_data = {
                **base_data,
                "raw_data": slack_data,
            }

            # Events API format
            if "event" in slack_data:
                event = slack_data["event"]
                parsed_data.update(
                    {
                        "event_type": event.get("type"),
                        "team_id": slack_data.get("team_id"),
                        "channel": event.get("channel"),
                        "user": event.get("user"),
                        "text": event.get("text"),
                        "thread_ts": event.get("thread_ts"),
                        "ts": event.get("ts") or event.get("event_ts"),
                        "files": event.get("files"),
                        "blocks": event.get("blocks"),
                    }
                )
            # Interactive payloads (block_actions, view_submission, shortcuts)
            elif slack_data.get("type") in (
                "block_actions",
                "view_submission",
                "shortcut",
                "message_action",
            ):
                parsed_data.update(
                    {
                        "event_type": slack_data.get("type"),
                        "team_id": slack_data.get("team", {}).get("id"),
                        "user": slack_data.get("user", {}).get("id"),
                        "channel": slack_data.get("channel", {}).get("id"),
                        "trigger_id": slack_data.get("trigger_id"),
                        "actions": slack_data.get("actions"),
                        "view": slack_data.get("view"),
                    }
                )
            # Slash commands (form-encoded, already parsed to dict)
            elif "command" in slack_data:
                parsed_data.update(
                    {
                        "event_type": "command",
                        "command": slack_data.get("command"),
                        "text": slack_data.get("text"),
                        "user": slack_data.get("user_id"),
                        "channel": slack_data.get("channel_id"),
                        "team_id": slack_data.get("team_id"),
                    }
                )
            # Outer-payload fallback
            else:
                parsed_data.update(
                    {
                        "team_id": slack_data.get("team_id"),
                        "channel": slack_data.get("channel_id"),
                        "user": slack_data.get("user_id"),
                        "text": slack_data.get("text"),
                        "ts": slack_data.get("ts"),
                    }
                )

            return parsed_data

        except Exception as e:
            logger.error(f"Error parsing Slack webhook: {e}")
            return {**base_data, "body": request_data.body, "parse_error": str(e)}

    async def _parse_github_webhook(
        self, request_data: WebhookRequestData, base_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Parse GitHub webhook data with rich event support."""
        try:
            if isinstance(request_data.body, dict):
                github_data = request_data.body
            else:
                github_data = json.loads(request_data.body)

            event_type = request_data.headers.get("x-github-event", "unknown")
            action = github_data.get("action")

            parsed_data = {
                **base_data,
                "event_type": f"{event_type}.{action}" if action else event_type,
                "github_event": event_type,
                "github_delivery": request_data.headers.get("x-github-delivery"),
                "action": action,
                "repository": {
                    "full_name": github_data.get("repository", {}).get("full_name"),
                    "url": github_data.get("repository", {}).get("html_url"),
                    "private": github_data.get("repository", {}).get("private"),
                }
                if github_data.get("repository")
                else None,
                "sender": {
                    "login": github_data.get("sender", {}).get("login"),
                    "avatar_url": github_data.get("sender", {}).get("avatar_url"),
                }
                if github_data.get("sender")
                else None,
                "raw_data": github_data,
            }

            # Event-specific fields
            if event_type == "push":
                parsed_data.update(
                    {
                        "ref": github_data.get("ref"),
                        "before": github_data.get("before"),
                        "after": github_data.get("after"),
                        "compare": github_data.get("compare"),
                        "commits": [
                            {
                                "id": c.get("id", "")[:8],
                                "message": c.get("message"),
                                "author": c.get("author", {}).get("name"),
                                "url": c.get("url"),
                            }
                            for c in (github_data.get("commits") or [])[:10]
                        ],
                        "forced": github_data.get("forced"),
                    }
                )
            elif event_type == "pull_request":
                pr = github_data.get("pull_request", {})
                parsed_data.update(
                    {
                        "number": pr.get("number"),
                        "title": pr.get("title"),
                        "body": (pr.get("body") or "")[:500],
                        "head_branch": pr.get("head", {}).get("ref"),
                        "base_branch": pr.get("base", {}).get("ref"),
                        "mergeable": pr.get("mergeable"),
                        "draft": pr.get("draft"),
                        "url": pr.get("html_url"),
                    }
                )
            elif event_type == "issues":
                issue = github_data.get("issue", {})
                parsed_data.update(
                    {
                        "number": issue.get("number"),
                        "title": issue.get("title"),
                        "body": (issue.get("body") or "")[:500],
                        "labels": [label.get("name") for label in (issue.get("labels") or [])],
                        "assignees": [a.get("login") for a in (issue.get("assignees") or [])],
                        "url": issue.get("html_url"),
                    }
                )
            elif event_type == "issue_comment":
                comment = github_data.get("comment", {})
                parsed_data.update(
                    {
                        "issue_number": github_data.get("issue", {}).get("number"),
                        "issue_title": github_data.get("issue", {}).get("title"),
                        "comment_body": (comment.get("body") or "")[:500],
                        "comment_user": comment.get("user", {}).get("login"),
                        "url": comment.get("html_url"),
                    }
                )
            elif event_type == "release":
                release = github_data.get("release", {})
                parsed_data.update(
                    {
                        "tag_name": release.get("tag_name"),
                        "name": release.get("name"),
                        "body": (release.get("body") or "")[:500],
                        "prerelease": release.get("prerelease"),
                        "draft": release.get("draft"),
                        "url": release.get("html_url"),
                    }
                )

            return parsed_data

        except Exception as e:
            logger.error(f"Error parsing GitHub webhook: {e}")
            return {**base_data, "body": request_data.body, "parse_error": str(e)}

    async def _parse_discord_webhook(
        self, request_data: WebhookRequestData, base_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Parse Discord webhook data with interaction support."""
        try:
            if isinstance(request_data.body, dict):
                discord_data = request_data.body
            else:
                discord_data = json.loads(request_data.body)

            # Handle Discord PING verification (required for interaction endpoints)
            if discord_data.get("type") == 1:
                return {
                    **base_data,
                    "_ping_response": True,
                    "type": 1,
                    "raw_data": discord_data,
                }

            parsed_data = {
                **base_data,
                "raw_data": discord_data,
            }

            # Gateway events (forwarded from bot)
            if "t" in discord_data:
                parsed_data.update(
                    {
                        "event_type": discord_data.get("t"),
                        "sequence": discord_data.get("s"),
                    }
                )
                d = discord_data.get("d", {})
                parsed_data.update(
                    {
                        "channel_id": d.get("channel_id"),
                        "guild_id": d.get("guild_id"),
                        "content": d.get("content"),
                        "author": {
                            "id": d.get("author", {}).get("id"),
                            "username": d.get("author", {}).get("username"),
                            "discriminator": d.get("author", {}).get("discriminator"),
                        }
                        if d.get("author")
                        else None,
                        "embeds": d.get("embeds"),
                        "attachments": d.get("attachments"),
                        "message_id": d.get("id"),
                    }
                )
            # Interaction payloads
            elif "type" in discord_data and discord_data["type"] in (2, 3, 4, 5):
                interaction_types = {
                    2: "APPLICATION_COMMAND",
                    3: "MESSAGE_COMPONENT",
                    4: "AUTOCOMPLETE",
                    5: "MODAL_SUBMIT",
                }
                parsed_data.update(
                    {
                        "event_type": f"INTERACTION_{interaction_types.get(discord_data['type'], 'UNKNOWN')}",
                        "interaction_id": discord_data.get("id"),
                        "interaction_token": discord_data.get("token"),
                        "channel_id": discord_data.get("channel_id"),
                        "guild_id": discord_data.get("guild_id"),
                        "member": discord_data.get("member"),
                        "data": discord_data.get("data"),
                    }
                )
            # Simple webhook message
            else:
                parsed_data.update(
                    {
                        "channel_id": discord_data.get("channel_id"),
                        "guild_id": discord_data.get("guild_id"),
                        "author": discord_data.get("author", {}).get("username")
                        if discord_data.get("author")
                        else None,
                        "content": discord_data.get("content"),
                    }
                )

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

    async def _parse_gmail_webhook(
        self, request_data: WebhookRequestData, base_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Parse Gmail Pub/Sub push notification."""
        try:
            import base64

            if isinstance(request_data.body, dict):
                pubsub_data = request_data.body
            else:
                pubsub_data = json.loads(request_data.body)

            # Google Pub/Sub wraps the notification
            message = pubsub_data.get("message", {})
            data_b64 = message.get("data", "")

            # Decode the base64 notification data
            decoded = {}
            if data_b64:
                try:
                    decoded = json.loads(base64.b64decode(data_b64).decode("utf-8"))
                except Exception:
                    decoded = {"raw": data_b64}

            parsed_data = {
                **base_data,
                "event_type": "message_received",
                "email_address": decoded.get("emailAddress"),
                "history_id": decoded.get("historyId"),
                "subscription": pubsub_data.get("subscription"),
                "message_id": message.get("messageId"),
                "publish_time": message.get("publishTime"),
                "raw_data": pubsub_data,
            }

            return parsed_data
        except Exception as e:
            logger.error(f"Error parsing Gmail webhook: {e}")
            return {**base_data, "body": request_data.body, "parse_error": str(e)}

    async def _parse_teams_webhook(
        self, request_data: WebhookRequestData, base_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Parse Microsoft Teams Bot Framework Activity."""
        try:
            if isinstance(request_data.body, dict):
                activity = request_data.body
            else:
                activity = json.loads(request_data.body)

            parsed_data = {
                **base_data,
                "event_type": activity.get("type", "message"),
                "activity_id": activity.get("id"),
                "channel_id": activity.get("channelId"),
                "conversation_id": activity.get("conversation", {}).get("id"),
                "from_id": activity.get("from", {}).get("id"),
                "from_name": activity.get("from", {}).get("name"),
                "text": activity.get("text"),
                "service_url": activity.get("serviceUrl"),
                "tenant_id": activity.get("channelData", {}).get("tenant", {}).get("id"),
                "raw_data": activity,
            }

            # Handle specific activity types
            if activity.get("type") == "conversationUpdate":
                parsed_data.update(
                    {
                        "members_added": [
                            m.get("name") for m in (activity.get("membersAdded") or [])
                        ],
                        "members_removed": [
                            m.get("name") for m in (activity.get("membersRemoved") or [])
                        ],
                    }
                )
            elif activity.get("type") == "messageReaction":
                parsed_data.update(
                    {
                        "reactions_added": activity.get("reactionsAdded"),
                        "reactions_removed": activity.get("reactionsRemoved"),
                    }
                )

            return parsed_data
        except Exception as e:
            logger.error(f"Error parsing Teams webhook: {e}")
            return {**base_data, "body": request_data.body, "parse_error": str(e)}
