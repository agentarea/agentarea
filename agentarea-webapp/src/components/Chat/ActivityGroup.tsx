"use client";

import { useState } from "react";
import { ChevronRight, Loader2 } from "lucide-react";
import type {
  A2UIAction,
  HumanInputSecretValue,
} from "@/components/Chat/types";
import {
  containsUnavailableToolValue,
  TOOL_DETAILS_UNAVAILABLE,
} from "@/components/Chat/utils/toolDetails";
import { summarizeToolGroup } from "@/components/Chat/utils/describeToolCall";
import { ToolIcon } from "@/components/Chat/utils/toolIcon";
import { PartRenderer } from "@/lib/events/parts/PartRenderer";
import { cn } from "@/lib/utils";
import type { ActivityRun } from "./activityView";

interface ActivityGroupProps {
  run: ActivityRun;
  onFormSubmit?: (
    id: string,
    answers: Record<string, unknown>,
    secrets: Record<string, HumanInputSecretValue>
  ) => void;
  onA2UIAction?: (
    action: A2UIAction,
    surfaceId: string,
    sourceComponentId: string
  ) => void;
}

export function ActivityGroup({
  run,
  onFormSubmit,
  onA2UIAction,
}: ActivityGroupProps) {
  const [userOpen, setUserOpen] = useState<boolean | null>(null);
  const open = userOpen ?? !run.completed;
  const hasUnavailableDetails = run.parts.some(
    (part) =>
      part.kind === "tool" &&
      [
        part.data.arguments,
        part.data.args,
        part.data.result,
        part.data.error,
        part.data.message,
        part.data.execution_time,
      ].some(containsUnavailableToolValue)
  );
  const summary = !run.completed
    ? "Working"
    : run.terminalType === "task.failed"
      ? "Work failed"
      : run.terminalType === "task.cancelled"
        ? "Work stopped"
        : "Work completed";
  const toolParts = run.parts.filter((part) => part.kind === "tool");
  const actionSummary = summarizeToolGroup(
    toolParts.map((part) =>
      typeof part.data.tool_name === "string"
        ? part.data.tool_name
        : typeof part.data.name === "string"
          ? part.data.name
          : "tool"
    )
  );
  const representative = toolParts[0];
  const representativeName = representative
    ? typeof representative.data.tool_name === "string"
      ? representative.data.tool_name
      : typeof representative.data.name === "string"
        ? representative.data.name
        : "tool"
    : "tool";
  const representativeIcon = representative
    ? typeof representative.data.server_icon === "string"
      ? representative.data.server_icon
      : typeof representative.data.mcp_server_icon === "string"
        ? representative.data.mcp_server_icon
        : typeof representative.data.icon_url === "string"
          ? representative.data.icon_url
          : typeof representative.data.server_icon_url === "string"
            ? representative.data.server_icon_url
            : undefined
    : undefined;

  return (
    <details open={open} className="min-w-0">
      <summary
        aria-expanded={open}
        onClick={(event) => {
          event.preventDefault();
          setUserOpen(!open);
        }}
        className="flex cursor-pointer list-none flex-wrap items-center gap-1.5 rounded-md px-2 py-1 text-[13px] leading-5 text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden"
      >
        {representative ? (
          <ToolIcon
            name={representativeName}
            iconUrl={representativeIcon}
            className="h-4 w-4 shrink-0 text-muted-foreground"
          />
        ) : null}
        {!run.completed && (
          <Loader2
            aria-hidden
            className="h-3 w-3 animate-spin motion-reduce:animate-none"
          />
        )}
        <span className="text-foreground/80">
          {actionSummary || summary}
        </span>
        <span className="text-muted-foreground/60" aria-hidden>
          ·
        </span>
        <span>{summary}</span>
        <span className="text-muted-foreground/60" aria-hidden>
          ·
        </span>
        <span>
          {run.actionCount} {run.actionCount === 1 ? "action" : "actions"}
        </span>
        {run.errorCount > 0 && (
          <span className="text-red-600 dark:text-red-400">
            · {run.errorCount} failed
          </span>
        )}
        <ChevronRight
          aria-hidden
          className={cn(
            "ml-auto h-3.5 w-3.5 transition-transform motion-reduce:transition-none",
            open && "rotate-90"
          )}
        />
      </summary>
      <div className="space-y-0.5 pb-1 pl-5">
        {run.parts.map((part) => (
          <PartRenderer
            key={part.partId}
            part={part}
            onFormSubmit={onFormSubmit}
            onA2UIAction={onA2UIAction}
            onToolInspect={() => setUserOpen(true)}
            suppressUnavailableDetails={hasUnavailableDetails}
          />
        ))}
        {hasUnavailableDetails && (
          <p className="px-1 pt-1 text-[11px] leading-5 text-muted-foreground/80">
            {TOOL_DETAILS_UNAVAILABLE}
          </p>
        )}
      </div>
    </details>
  );
}

export default ActivityGroup;
