"""A trigger's own configuration rules, independent of the service that stores it."""

from .condition_models import ModelInstances, validate_condition_models
from .domain.enums import TriggerType
from .domain.models import TriggerCreate
from .logging_utils import TriggerValidationError


async def validate_trigger_configuration(
    trigger_data: TriggerCreate, model_instances: ModelInstances
) -> None:
    """Validate trigger configuration based on type.

    Reads nothing but the model instances an LLM condition names, so it runs
    before the trigger's agent exists.

    Args:
        trigger_data: The trigger creation data
        model_instances: The workspace's model instances

    Raises:
        TriggerValidationError: If configuration is invalid
    """
    # Basic validation
    if not trigger_data.name or not trigger_data.name.strip():
        raise TriggerValidationError("Trigger name is required")

    if not trigger_data.created_by or not trigger_data.created_by.strip():
        raise TriggerValidationError("Trigger created_by is required")

    await validate_condition_models(trigger_data.conditions, model_instances)

    # Type-specific validation
    if trigger_data.trigger_type == TriggerType.CRON:
        await _validate_cron_configuration(trigger_data)
    elif trigger_data.trigger_type == TriggerType.WEBHOOK:
        await _validate_webhook_configuration(trigger_data)


async def _validate_cron_configuration(trigger_data: TriggerCreate) -> None:
    """Validate cron trigger configuration.

    Args:
        trigger_data: The trigger creation data

    Raises:
        TriggerValidationError: If cron configuration is invalid
    """
    if not trigger_data.cron_expression:
        raise TriggerValidationError("Cron expression is required for CRON triggers")

    # Basic cron expression validation
    parts = trigger_data.cron_expression.strip().split()
    if len(parts) not in [5, 6]:
        raise TriggerValidationError("Cron expression must have 5 or 6 parts")

    # Validate timezone
    if not trigger_data.timezone or not trigger_data.timezone.strip():
        raise TriggerValidationError("Timezone is required for CRON triggers")

    # A schedule coming due carries nothing with it, so the task text is the
    # only thing that can tell the agent what to do. Two exemptions, both
    # because something else supplies the text: webhooks get it from the
    # call, and a schedule with a data extractor polls a mailbox or a feed
    # and works on what it finds.
    if not trigger_data.data_extractor:
        task_text = (trigger_data.task_parameters or {}).get("text")
        if not isinstance(task_text, str) or not task_text.strip():
            raise TriggerValidationError("Task text is required for CRON triggers")


async def _validate_webhook_configuration(trigger_data: TriggerCreate) -> None:
    """Validate webhook trigger configuration.

    Args:
        trigger_data: The trigger creation data

    Raises:
        TriggerValidationError: If webhook configuration is invalid
    """
    if not trigger_data.webhook_id:
        raise TriggerValidationError("Webhook ID is required for WEBHOOK triggers")

    # Validate HTTP methods
    if not trigger_data.allowed_methods:
        raise TriggerValidationError("At least one HTTP method must be allowed")

    valid_methods = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
    for method in trigger_data.allowed_methods:
        if method.upper() not in valid_methods:
            raise TriggerValidationError(f"Invalid HTTP method: {method}")
