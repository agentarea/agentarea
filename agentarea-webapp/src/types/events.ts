import type {
  TaskEvent as ApiTaskEvent,
  TaskEventResponse as ApiTaskEventResponse,
} from "@/api/client/types.gen";

// Base types from API schema
export type TaskEvent = ApiTaskEvent;
export type TaskEventResponse = ApiTaskEventResponse;

// UI-friendly event representation
export interface DisplayEvent {
  id: string;
  type: string;
  /** Null when the event arrived without one — never replaced by "now". */
  timestamp: Date | null;
  title: string;
  description: string;
  level: EventLevel;
  data?: Record<string, unknown>;
  icon?: string;
}

export type EventLevel = "info" | "success" | "warning" | "error";
