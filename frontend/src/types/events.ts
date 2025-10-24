import { components } from "@/api/schema";

// Base types from API schema
export type TaskEvent = components["schemas"]["TaskEvent"];
export type TaskEventResponse = components["schemas"]["TaskEventResponse"];

// Extended SSE event types
export interface SSEEvent {
  event_type: string;
  timestamp: string;
  data: Record<string, any>;
}

// Specific event type definitions based on our backend implementation
export type WorkflowEventType =
  | "WorkflowStarted"
  | "WorkflowCompleted"
  | "WorkflowFailed"
  | "WorkflowCancelled"
  | "IterationStarted"
  | "IterationCompleted"
  | "LLMCallStarted"
  | "LLMCallCompleted"
  | "LLMCallFailed"
  | "ToolCallStarted"
  | "ToolCallCompleted"
  | "ToolCallFailed"
  | "BudgetWarning"
  | "BudgetExceeded"
  | "HumanApprovalRequested"
  | "HumanApprovalReceived";

// SSE message format (what we receive over SSE) - matches protocol structure
export interface SSEMessage {
  event: string;
  data: {
    event_type: WorkflowEventType;
    event_id: string;
    timestamp: string;
    data: {
      // Core workflow fields
      task_id: string;
      agent_id?: string;
      execution_id?: string;
      iteration?: number;

      // LLM event fields
      content?: string;
      cost?: number;
      usage?: {
        input_tokens?: number;
        output_tokens?: number;
        total_tokens?: number;
      };
      tool_calls?: Array<{
        name: string;
        arguments: any;
      }>;
      model_id?: string;

      // Tool event fields
      tool_name?: string;
      result?: any;
      success?: boolean;

      // Chunk event fields
      chunk?: string;
      chunk_index?: number;
      is_final?: boolean;

      // Error fields
      error?: string;
      error_type?: string;
    };
  };
}

// UI-friendly event representation
export interface DisplayEvent {
  id: string;
  type: WorkflowEventType;
  timestamp: Date;
  title: string;
  description: string;
  level: EventLevel;
  data?: Record<string, any>;
  icon?: string;
}

export type EventLevel = "info" | "success" | "warning" | "error";

// Event filtering options
export interface EventFilters {
  eventTypes?: WorkflowEventType[];
  levels?: EventLevel[];
  search?: string;
  dateRange?: {
    start: Date;
    end: Date;
  };
}

// Real-time event state
export interface EventsState {
  events: DisplayEvent[];
  loading: boolean;
  error: string | null;
  connected: boolean;
  filters: EventFilters;
  pagination: {
    page: number;
    pageSize: number;
    total: number;
    hasNext: boolean;
  };
}

// Event statistics
export interface EventStats {
  total: number;
  byType: Record<WorkflowEventType, number>;
  byLevel: Record<EventLevel, number>;
  recentActivity: number; // events in last hour
}

// Hook options for useTaskEvents
export interface UseTaskEventsOptions {
  includeHistory?: boolean;
  autoConnect?: boolean;
  filters?: EventFilters;
  onEvent?: (event: DisplayEvent) => void;
  onError?: (error: string) => void;
  onConnected?: () => void;
  onDisconnected?: () => void;
}

// Helper functions for event mapping
export const EVENT_TYPE_CONFIG: Record<
  WorkflowEventType,
  {
    title: string;
    level: EventLevel;
    icon: string;
    color: string;
  }
> = {
  WorkflowStarted: {
    title: "Workflow Started",
    level: "info",
    icon: "play-circle",
    color: "blue",
  },
  WorkflowCompleted: {
    title: "Workflow Completed",
    level: "success",
    icon: "check-circle",
    color: "green",
  },
  WorkflowFailed: {
    title: "Workflow Failed",
    level: "error",
    icon: "x-circle",
    color: "red",
  },
  WorkflowCancelled: {
    title: "Workflow Cancelled",
    level: "warning",
    icon: "stop-circle",
    color: "yellow",
  },
  IterationStarted: {
    title: "Iteration Started",
    level: "info",
    icon: "refresh-cw",
    color: "blue",
  },
  IterationCompleted: {
    title: "Iteration Completed",
    level: "success",
    icon: "check",
    color: "green",
  },
  LLMCallStarted: {
    title: "LLM Call Started",
    level: "info",
    icon: "brain",
    color: "purple",
  },
  LLMCallCompleted: {
    title: "LLM Response Received",
    level: "success",
    icon: "message-circle",
    color: "purple",
  },
  LLMCallFailed: {
    title: "LLM Call Failed",
    level: "error",
    icon: "alert-triangle",
    color: "red",
  },
  ToolCallStarted: {
    title: "Tool Execution Started",
    level: "info",
    icon: "tool",
    color: "orange",
  },
  ToolCallCompleted: {
    title: "Tool Execution Completed",
    level: "success",
    icon: "check-square",
    color: "orange",
  },
  ToolCallFailed: {
    title: "Tool Execution Failed",
    level: "error",
    icon: "alert-circle",
    color: "red",
  },
  BudgetWarning: {
    title: "Budget Warning",
    level: "warning",
    icon: "dollar-sign",
    color: "yellow",
  },
  BudgetExceeded: {
    title: "Budget Exceeded",
    level: "error",
    icon: "credit-card",
    color: "red",
  },
  HumanApprovalRequested: {
    title: "Human Approval Requested",
    level: "warning",
    icon: "user-check",
    color: "indigo",
  },
  HumanApprovalReceived: {
    title: "Human Approval Received",
    level: "success",
    icon: "user-check",
    color: "green",
  },
};

// Utility functions
export const mapSSEToDisplayEvent = (
  sseEvent: SSEMessage,
  id?: string
): DisplayEvent => {
  // Map event names to our internal event types - handle both PascalCase and snake_case
  const eventTypeMap: Record<string, WorkflowEventType> = {
    workflow_started: "WorkflowStarted",
    workflowstarted: "WorkflowStarted",
    workflow_completed: "WorkflowCompleted",
    workflowcompleted: "WorkflowCompleted",
    workflow_failed: "WorkflowFailed",
    workflowfailed: "WorkflowFailed",
    workflow_cancelled: "WorkflowCancelled",
    workflowcancelled: "WorkflowCancelled",
    iteration_started: "IterationStarted",
    iterationstarted: "IterationStarted",
    iteration_completed: "IterationCompleted",
    iterationcompleted: "IterationCompleted",
    llm_call_started: "LLMCallStarted",
    llmcallstarted: "LLMCallStarted",
    llm_call_completed: "LLMCallCompleted",
    llmcallcompleted: "LLMCallCompleted",
    llm_call_failed: "LLMCallFailed",
    llmcallfailed: "LLMCallFailed",
    llm_call_chunk: "LLMCallCompleted", // Map chunks to completed for display
    llmcallchunk: "LLMCallCompleted",
    tool_call_started: "ToolCallStarted",
    toolcallstarted: "ToolCallStarted",
    tool_call_completed: "ToolCallCompleted",
    toolcallcompleted: "ToolCallCompleted",
    tool_call_failed: "ToolCallFailed",
    toolcallfailed: "ToolCallFailed",
    budget_warning: "BudgetWarning",
    budgetwarning: "BudgetWarning",
    budget_exceeded: "BudgetExceeded",
    budgetexceeded: "BudgetExceeded",
    human_approval_requested: "HumanApprovalRequested",
    humanapprovalrequested: "HumanApprovalRequested",
    human_approval_received: "HumanApprovalReceived",
    humanapprovalreceived: "HumanApprovalReceived",
    task_completed: "WorkflowCompleted",
    taskcompleted: "WorkflowCompleted",
    task_failed: "WorkflowFailed",
    taskfailed: "WorkflowFailed",
  };

  // Get the mapped event type - try event name first, then event_type field
  const eventKey = sseEvent.event.toLowerCase().replace(/[^a-z]/g, "");
  const eventTypeKey =
    sseEvent.data.event_type?.toLowerCase().replace(/[^a-z]/g, "") || "";

  const mappedEventType =
    eventTypeMap[eventKey] ||
    eventTypeMap[eventTypeKey] ||
    (sseEvent.data.event_type as WorkflowEventType) ||
    "WorkflowStarted";

  const config = EVENT_TYPE_CONFIG[mappedEventType];
  const eventData = sseEvent.data.data;

  // Create meaningful descriptions based on event content
  let description = config?.title || mappedEventType;

  // Check for content in tool_calls (like task_complete results)
  if (eventData.tool_calls && eventData.tool_calls.length > 0) {
    const toolCall = eventData.tool_calls[0];
    if (toolCall.name === "task_complete") {
      try {
        const args =
          typeof toolCall.arguments === "string"
            ? JSON.parse(toolCall.arguments)
            : toolCall.arguments;
        description = `Task completed: ${args.summary || args.result || "Success"}`;
      } catch (e) {
        description = `Task completed with ${toolCall.name}`;
      }
    } else {
      description = `${config?.title}: ${toolCall.name}`;
    }
  } else if (eventData.content) {
    description = eventData.chunk
      ? `AI is responding: ${eventData.chunk.substring(0, 100)}${eventData.chunk.length > 100 ? "..." : ""}`
      : `AI responded: ${eventData.content.substring(0, 100)}${eventData.content.length > 100 ? "..." : ""}`;
  } else if (eventData.tool_name) {
    description = `${config?.title}: ${eventData.tool_name}`;
  } else if (eventData.error) {
    description = `${config?.title}: ${eventData.error}`;
  } else if (eventData.cost) {
    description = `${config?.title} (Cost: $${eventData.cost.toFixed(4)})`;
  } else if (eventData.iteration) {
    description = `${config?.title} ${eventData.iteration}`;
  }

  return {
    id: id || `${eventData.task_id}-${mappedEventType}-${Date.now()}`,
    type: mappedEventType,
    timestamp: new Date(sseEvent.data.timestamp),
    title: config?.title || mappedEventType,
    description,
    level: config?.level || "info",
    data: eventData,
    icon: config?.icon,
  };
};

export const mapTaskEventToDisplayEvent = (
  taskEvent: TaskEvent
): DisplayEvent => {
  const eventType = taskEvent.event_type as WorkflowEventType;
  const config = EVENT_TYPE_CONFIG[eventType];

  return {
    id: taskEvent.id,
    type: eventType,
    timestamp: new Date(taskEvent.timestamp),
    title: config?.title || taskEvent.event_type,
    description: taskEvent.message,
    level: config?.level || "info",
    data: taskEvent.metadata,
    icon: config?.icon,
  };
};

export const getEventLevelColor = (level: EventLevel): string => {
  switch (level) {
    case "success":
      return "text-green-600 bg-green-50 border-green-200";
    case "error":
      return "text-red-600 bg-red-50 border-red-200";
    case "warning":
      return "text-yellow-600 bg-yellow-50 border-yellow-200";
    default:
      return "text-blue-600 bg-blue-50 border-blue-200";
  }
};

export const getEventStats = (events: DisplayEvent[]): EventStats => {
  const now = new Date();
  const oneHourAgo = new Date(now.getTime() - 60 * 60 * 1000);

  return {
    total: events.length,
    byType: events.reduce(
      (acc, event) => {
        acc[event.type] = (acc[event.type] || 0) + 1;
        return acc;
      },
      {} as Record<WorkflowEventType, number>
    ),
    byLevel: events.reduce(
      (acc, event) => {
        acc[event.level] = (acc[event.level] || 0) + 1;
        return acc;
      },
      {} as Record<EventLevel, number>
    ),
    recentActivity: events.filter((event) => event.timestamp > oneHourAgo)
      .length,
  };
};
