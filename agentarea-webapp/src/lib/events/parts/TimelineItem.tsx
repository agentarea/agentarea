import React from "react";
import { StatusIndicator } from "@/components/ui/status-indicator";
import type { TimelineItem as TimelineEntry } from "../reducer";
import {
  TASK_COMPLETED,
  TASK_FAILED,
  TASK_CANCELLED,
} from "../contract";

function asString(value: unknown): string | undefined {
  return typeof value === "string" && value ? value : undefined;
}

/** Renders a lifecycle/terminal task.* event as a status line. */
export const TimelineItem: React.FC<{ item: TimelineEntry }> = ({ item }) => {
  const message =
    asString(item.data.message) ?? asString(item.data.reason) ?? item.eventType;

  if (item.eventType === TASK_COMPLETED) {
    return <StatusIndicator tone="success">{message}</StatusIndicator>;
  }
  if (item.eventType === TASK_FAILED) {
    return <StatusIndicator tone="danger">{message}</StatusIndicator>;
  }
  if (item.eventType === TASK_CANCELLED) {
    return <StatusIndicator tone="neutral">{message}</StatusIndicator>;
  }
  return <StatusIndicator tone="info">{message}</StatusIndicator>;
};

export default TimelineItem;
