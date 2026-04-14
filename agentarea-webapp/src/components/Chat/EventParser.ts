import { A2UISurface, MessageComponentType } from "./types";

// FIXME: Performance — this is a large switch statement that runs synchronously per-event
// on every call from the useMemo chain in page.tsx. Adding new event types increases the
// worst-case cost. Should be refactored to a dispatch map (Record<string, handler>) so
// lookup is O(1) instead of O(n switch cases), and to avoid re-running for cached events.
// Parse event data into appropriate message component type
export const parseEventToMessage = (
  eventType: string,
  eventData: any
): MessageComponentType | null => {
  const baseData = {
    id: eventData.task_id || eventData.aggregate_id || Date.now().toString(),
    timestamp: eventData.timestamp || new Date().toISOString(),
    agent_id: eventData.agent_id || "",
    event_type: eventType,
  };

  switch (eventType) {
    case "LLMCallCompleted": {
      // Extract content and usage information
      const originalData = eventData.original_data || eventData;
      const content = originalData.content || eventData.content;
      const thinking = originalData.thinking || eventData.thinking || "";

      // Only create message if there's actual content
      if (!content || !content.trim()) return null;

      return {
        type: "llm_response",
        data: {
          ...baseData,
          content,
          thinking: thinking || undefined,
          role: originalData.role || eventData.role || "assistant",
          tool_calls: originalData.tool_calls || eventData.tool_calls,
          usage: originalData.usage || eventData.usage,
        },
      };
    }

    case "LLMCallChunk": {
      // Extract chunk information for streaming display
      const originalData = eventData.original_data || eventData;
      const chunk = originalData.chunk || eventData.chunk;
      const chunkIndex = originalData.chunk_index || eventData.chunk_index || 0;
      const isFinal = originalData.is_final || eventData.is_final || false;
      const chunkType = originalData.chunk_type || eventData.chunk_type || "text";

      // Create or update streaming message
      // Note: This requires special handling in the chat component to accumulate chunks
      return {
        type: "llm_chunk",
        data: {
          ...baseData,
          chunk,
          chunk_index: chunkIndex,
          is_final: isFinal,
          chunk_type: chunkType,
        },
      };
    }

    case "LLMCallFailed": {
      // Extract enriched error information
      const originalData = eventData.original_data || eventData;
      const error = originalData.error || eventData.error;
      const errorType = originalData.error_type || eventData.error_type;

      // Only create message if there's an error
      if (!error) return null;

      // Build user-friendly error message based on error type
      let displayMessage = error;
      const modelId = originalData.model_id || eventData.model_id;
      const providerType =
        originalData.provider_type || eventData.provider_type;

      if (originalData.is_auth_error || eventData.is_auth_error) {
        displayMessage = `Authentication failed${providerType ? ` for ${providerType}` : ""}. Please check your API key configuration.`;
      } else if (
        originalData.is_rate_limit_error ||
        eventData.is_rate_limit_error
      ) {
        const retryAfter = originalData.retry_after || eventData.retry_after;
        displayMessage = `Rate limit exceeded${providerType ? ` for ${providerType}` : ""}${retryAfter ? `. Retry after ${retryAfter} seconds.` : "."}`;
      } else if (originalData.is_quota_error || eventData.is_quota_error) {
        const quotaType = originalData.quota_type || eventData.quota_type;
        displayMessage = `Quota exceeded${quotaType ? ` (${quotaType})` : ""}${providerType ? ` for ${providerType}` : ""}. Please check your billing settings.`;
      } else if (originalData.is_model_error || eventData.is_model_error) {
        displayMessage = `Model not found${modelId ? `: ${modelId}` : ""}${providerType ? ` on ${providerType}` : ""}.`;
      } else if (originalData.is_network_error || eventData.is_network_error) {
        const statusCode = originalData.status_code || eventData.status_code;
        displayMessage = `Network error${statusCode ? ` (${statusCode})` : ""}${providerType ? ` connecting to ${providerType}` : ""}.`;
      }

      return {
        type: "error",
        data: {
          ...baseData,
          error: displayMessage,
          error_type: errorType,
          // Include additional context for debugging
          raw_error: error,
          is_auth_error:
            originalData.is_auth_error || eventData.is_auth_error || false,
          is_rate_limit_error:
            originalData.is_rate_limit_error ||
            eventData.is_rate_limit_error ||
            false,
          is_quota_error:
            originalData.is_quota_error || eventData.is_quota_error || false,
          is_model_error:
            originalData.is_model_error || eventData.is_model_error || false,
          is_network_error:
            originalData.is_network_error ||
            eventData.is_network_error ||
            false,
          retryable:
            originalData.retryable !== false && eventData.retryable !== false, // Default to true
        },
      };
    }

    case "ToolCallStarted": {
      // Extract tool call start information
      const originalData = eventData.original_data || eventData;
      const toolName = originalData.tool_name || eventData.tool_name;
      const toolCallId = originalData.tool_call_id || eventData.tool_call_id;
      const toolArguments = originalData.arguments || eventData.arguments || {};

      // If no tool name, create a generic tool call message
      const displayToolName = toolName || "Unknown Tool";

      const result = {
        type: "tool_call_started" as const,
        data: {
          ...baseData,
          tool_name: displayToolName,
          tool_call_id: toolCallId || "unknown",
          arguments: toolArguments,
        },
      };

      return result;
    }

    case "ToolCallCompleted": {
      // Extract tool result information
      const originalData = eventData.original_data || eventData;
      const result = originalData.result || eventData.result;
      const toolName = originalData.tool_name || eventData.tool_name;
      const toolCallId = originalData.tool_call_id || eventData.tool_call_id;

      // If no tool name or result, create a generic tool completion message
      const displayToolName = toolName || "Unknown Tool";
      const displayResult =
        result || "Tool execution completed (no result data)";

      const resultComponent = {
        type: "tool_result" as const,
        data: {
          ...baseData,
          tool_name: displayToolName,
          tool_call_id: toolCallId || "unknown",
          result: displayResult,
          success: originalData.success ?? eventData.success ?? true,
          execution_time:
            originalData.execution_time || eventData.execution_time,
          arguments: originalData.arguments || eventData.arguments,
        },
      };

      return resultComponent;
    }

    case "ToolCallFailed": {
      // Extract tool failure information
      const originalData = eventData.original_data || eventData;
      const error = originalData.error || eventData.error;
      const toolName = originalData.tool_name || eventData.tool_name;

      // Only create message if there's an error and tool name
      if (!error || !toolName) return null;

      return {
        type: "error",
        data: {
          ...baseData,
          error: `Tool "${toolName}" failed: ${error}`,
          error_type: "tool_call_failed",
          tool_name: toolName,
          arguments: originalData.arguments || eventData.arguments,
        },
      };
    }

    case "WorkflowCompleted": {
      // Extract final workflow result
      const result = eventData.result || eventData.final_response;
      const originalData = eventData.original_data || eventData;

      // Only create message if there's a meaningful result
      if (!result || !result.trim()) return null;

      return {
        type: "workflow_result",
        data: {
          ...baseData,
          result,
          final_response: eventData.final_response,
          success: true,
          iterations_completed:
            originalData.iterations_completed || eventData.iterations_completed,
          total_cost: originalData.total_cost || eventData.total_cost,
        },
      };
    }

    case "WorkflowFailed":
    case "task_failed": {
      // Extract error information
      const rawError = eventData.error || eventData.message;
      const originalData = eventData.original_data || eventData;

      // Only create message if there's an error
      if (!rawError) return null;

      // Sanitize internal errors into user-friendly messages
      const error = sanitizeWorkflowError(rawError);

      return {
        type: "error",
        data: {
          ...baseData,
          error,
          error_type: originalData.error_type || eventData.error_type,
          raw_error: rawError,
        },
      };
    }

    // System-level events (optional - for debugging/info)
    case "WorkflowStarted": {
      const goalDescription =
        eventData.goal_description || eventData.original_data?.goal_description;
      if (!goalDescription) return null;

      return {
        type: "system",
        data: {
          ...baseData,
          message: `Task started: ${goalDescription}`,
          level: "info",
        },
      };
    }

    case "BudgetWarning": {
      const message =
        eventData.message ||
        `Budget warning: ${eventData.usage_percentage}% used`;
      return {
        type: "system",
        data: {
          ...baseData,
          message,
          level: "warning",
        },
      };
    }

    case "BudgetExceeded": {
      const message =
        eventData.message ||
        `Budget exceeded: $${eventData.cost}/$${eventData.limit}`;
      return {
        type: "system",
        data: {
          ...baseData,
          message,
          level: "error",
        },
      };
    }

    case "A2UICreateSurface": {
      const d = eventData.original_data || eventData;
      const surfaceId = d.surface_id || eventData.surface_id;
      if (!surfaceId) return null;

      const surface: A2UISurface = {
        surfaceId,
        catalogId: d.catalog_id || "https://a2ui.org/specification/v0_9/basic_catalog.json",
        theme: d.theme,
        sendDataModel: d.send_data_model ?? false,
        components: {},
        dataModel: {},
      };

      return {
        type: "a2ui_surface",
        data: {
          ...baseData,
          surfaceId,
          surface,
        },
      };
    }

    case "HumanApprovalRequested": {
      const originalData = eventData.original_data || eventData;
      return {
        type: "approval_request",
        data: {
          ...baseData,
          escalation_id: originalData.escalation_id || eventData.escalation_id,
          tool_name: originalData.tool_name || eventData.tool_name,
          tool_call_id: originalData.tool_call_id || eventData.tool_call_id,
          arguments: originalData.arguments || eventData.arguments || {},
          message: originalData.message || eventData.message || "Approval required",
          resolved: eventData.resolved ?? originalData.resolved ?? false,
          approved: eventData.approved ?? originalData.approved,
          deny_comment: eventData.deny_comment ?? originalData.deny_comment,
        },
      };
    }

    case "MessageQueued": {
      const originalData = eventData.original_data || eventData;
      const content = originalData.content || eventData.content || eventData.message;
      if (!content) return null;

      return {
        type: "user_message",
        data: {
          ...baseData,
          content,
        },
      };
    }

    // A2UIUpdateComponents, A2UIUpdateDataModel, A2UIDeleteSurface are handled
    // via setMessages mutation in messageEventHandlers — they return null here.
    case "A2UIUpdateComponents":
    case "A2UIUpdateDataModel":
    case "A2UIDeleteSurface":
    case "HumanApprovalDenied":
    case "HumanApprovalReceived":
      // These update existing messages, handled in eventHandlers
      return null;

    default:
      // For unhandled event types, return null (don't display)
      return null;
  }
};

// Sanitize internal workflow errors into user-friendly messages
const sanitizeWorkflowError = (rawError: string): string => {
  const lower = rawError.toLowerCase();

  // Agent configuration errors
  if (lower.includes("build_agent_config") || lower.includes("agentconfigresult")) {
    if (lower.includes("model_id")) {
      return "Agent configuration error: no model is assigned. Please configure a model in agent settings.";
    }
    return "Agent configuration error. Please check the agent settings.";
  }

  // LLM / provider errors
  if (lower.includes("call_llm_activity") || lower.includes("call_llm")) {
    if (lower.includes("auth") || lower.includes("api_key") || lower.includes("unauthorized")) {
      return "Authentication failed with the LLM provider. Please check your API key configuration.";
    }
    if (lower.includes("rate_limit") || lower.includes("429")) {
      return "Rate limit exceeded. Please try again in a moment.";
    }
    if (lower.includes("timeout")) {
      return "The LLM request timed out. Please try again.";
    }
    if (lower.includes("deprecated")) {
      return "The configured model has been deprecated by the provider. Please select a different model.";
    }
    if (lower.includes("not found") || lower.includes("notfounderror") || lower.includes("404")) {
      return "The configured model was not found. Please check the model name or select a different one.";
    }
    return "Failed to get a response from the AI model. Please try again.";
  }

  // Tool execution errors
  if (lower.includes("execute_mcp_tool") || lower.includes("tool_execution")) {
    return "A tool execution failed. Please check the tool configuration.";
  }

  // Budget errors
  if (lower.includes("budget")) {
    return "Task budget has been exceeded.";
  }

  // Generic activity failures — extract just the activity name
  const activityMatch = rawError.match(/activity=(\w+)/);
  if (activityMatch) {
    return `Task failed during ${activityMatch[1].replace(/_activity$/, "").replace(/_/g, " ")}. Please try again.`;
  }

  // Fallback — truncate and remove internal details
  const firstLine = rawError.split("\n")[0];
  if (firstLine.length > 150) {
    return firstLine.substring(0, 147) + "...";
  }
  return firstLine;
};

// Helper to determine if event should create a visible message
export const shouldDisplayEvent = (eventType: string): boolean => {
  const displayableEvents = [
    "LLMCallCompleted",
    "LLMCallChunk",
    "LLMCallFailed",
    "ToolCallStarted",
    "ToolCallCompleted",
    "ToolCallFailed",
    "WorkflowCompleted",
    "WorkflowFailed",
    "task_completed",
    "task_failed",
    "task_cancelled",
    "BudgetWarning",
    "BudgetExceeded",
    "A2UICreateSurface",
    "A2UIUpdateComponents",
    "A2UIUpdateDataModel",
    "A2UIDeleteSurface",
    "HumanApprovalRequested",
    "MessageQueued",
  ];

  return displayableEvents.includes(eventType);
};
