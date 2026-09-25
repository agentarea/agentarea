"""Turning Temporal failures into diagnostics and user-facing messages."""

from temporalio.exceptions import ActivityError, ApplicationError

from .base import AgentWorkflowBase


class ErrorReportingMixin(AgentWorkflowBase):
    """Turning Temporal failures into diagnostics and user-facing messages."""

    @staticmethod
    def _get_user_facing_error(error: Exception) -> str:
        """Return a short, user-friendly error message (no stack traces)."""
        msg = str(error).lower()
        cause_msg = ""
        if isinstance(error, ActivityError) and error.cause:
            cause_msg = str(error.cause).lower()

        activity_name = ""
        if isinstance(error, ActivityError) and error.activity_type:
            activity_name = error.activity_type.lower()

        combined = f"{msg} {cause_msg} {activity_name}"

        if "model_id" in combined and ("none" in combined or "valid string" in combined):
            return "No model is configured for this agent. Please assign a model in agent settings."
        if "build_agent_config" in combined:
            return "Agent configuration error. Please check the agent settings."
        if "call_llm" in combined:
            if "auth" in combined or "api_key" in combined or "unauthorized" in combined:
                return "Authentication failed with the LLM provider. Please check your API key."
            if "rate_limit" in combined or "429" in combined:
                return "Rate limit exceeded. Please try again in a moment."
            if "timeout" in combined:
                return "The AI model request timed out. Please try again."
            if "deprecated" in combined:
                return "The configured model has been deprecated by the provider. Please select a different model."
            if "not found" in combined or "notfounderror" in combined or "404" in combined:
                return "The configured model was not found. Please check the model name or select a different one."
            return "Failed to get a response from the AI model."
        if "execute_mcp_tool" in combined or "tool_execution" in combined:
            return "A tool execution failed during the task."
        if "budget" in combined:
            return "Task budget has been exceeded."
        if "compact_messages" in combined:
            return "Failed to manage conversation context. Please try again."

        # Generic fallback — activity name only, no internals
        if isinstance(error, ActivityError) and error.activity_type:
            activity = error.activity_type.replace("_activity", "").replace("_", " ")
            return f"Task failed during {activity}. Please try again."

        return "An unexpected error occurred. Please try again."

    @staticmethod
    def _get_user_facing_error_type(error: Exception) -> str:
        """Return a human-readable error category instead of raw Python class names."""
        combined = str(error).lower()
        if isinstance(error, ActivityError):
            if error.cause:
                combined += " " + str(error.cause).lower()

        if "auth" in combined or "api_key" in combined or "unauthorized" in combined:
            return "AuthenticationError"
        if "rate_limit" in combined or "429" in combined:
            return "RateLimitError"
        if "deprecated" in combined:
            return "ModelDeprecated"
        if "not found" in combined or "notfounderror" in combined or "404" in combined:
            return "ModelNotFound"
        if "timeout" in combined:
            return "TimeoutError"
        if "budget" in combined or "quota" in combined:
            return "BudgetExceeded"
        if "model_id" in combined and "none" in combined:
            return "ConfigurationError"
        return "Error"

    def _extract_temporal_error_details(self, error: Exception) -> str:
        """Extract actionable details from Temporal errors (Activity/ApplicationError)."""
        if isinstance(error, ActivityError):
            parts = [str(error)]
            if error.activity_type:
                parts.append(f"activity={error.activity_type}")
            if error.retry_state:
                parts.append(f"retry_state={error.retry_state}")

            cause = error.cause
            if cause is not None:
                parts.append(f"cause={cause!s}")
                if isinstance(cause, ApplicationError):
                    if cause.type:
                        parts.append(f"cause_type={cause.type}")
                    if cause.details:
                        parts.append(f"cause_details={cause.details}")
            return " | ".join(parts)

        if isinstance(error, ApplicationError):
            parts = [str(error)]
            if error.type:
                parts.append(f"type={error.type}")
            if error.details:
                parts.append(f"details={error.details}")
            return " | ".join(parts)

        return str(error)
