import React from "react";
import type { Part } from "../contract";
import {
  describeToolCall,
  type ToolMeta,
} from "@/components/Chat/utils/describeToolCall";
import { FileChip } from "@/components/Chat/utils/fileIcon";
import { StatusIndicator } from "@/components/ui/status-indicator";

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : undefined;
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((v): v is string => typeof v === "string")
    : [];
}

/**
 * Codex-style tool card. In-flight (tool.call) pulses; tool.result reports
 * success/failure. A script run that exits nonzero shows as failed even when the
 * transport reported success, and any written files appear as chips.
 */
export const ToolPart: React.FC<{ part: Part }> = ({ part }) => {
  const data = part.data;
  const toolName =
    (typeof data.tool_name === "string" && data.tool_name) ||
    (typeof data.name === "string" && data.name) ||
    "tool";
  const args = asRecord(data.arguments) ?? asRecord(data.args);
  const exitCode =
    typeof data.exit_code === "number" ? data.exit_code : null;
  const meta: ToolMeta = {
    skill_name:
      typeof data.skill_name === "string" ? data.skill_name : undefined,
    script_name:
      typeof data.script_name === "string" ? data.script_name : undefined,
    exit_code: exitCode,
    artifact_paths: asStringArray(data.artifact_paths),
  };

  const { text, code } = describeToolCall(toolName, args, meta);

  const inFlight = part.eventType === "tool.call";
  // A script's exit code is the source of truth; fall back to the boolean
  // success flag only when no exit code was reported.
  const success =
    exitCode == null ? data.success !== false : exitCode === 0;

  const artifactPaths = asStringArray(data.artifact_paths);

  let tone: "info" | "success" | "danger" = "info";
  let statusLabel: string = text;
  if (inFlight) {
    tone = "info";
  } else if (success) {
    tone = "success";
    statusLabel = text;
  } else {
    tone = "danger";
    statusLabel = exitCode != null ? `${text} · exit ${exitCode}` : text;
  }

  return (
    <div className="flex flex-col gap-1.5 rounded-md border border-border bg-muted/30 px-3 py-2">
      <div className="flex items-center gap-2">
        <StatusIndicator tone={tone} pulse={inFlight}>
          {statusLabel}
        </StatusIndicator>
        {code ? (
          <code className="truncate rounded bg-muted px-1.5 py-0.5 font-mono text-xs text-muted-foreground">
            {code}
          </code>
        ) : null}
      </div>
      {artifactPaths.length > 0 ? (
        <div className="flex flex-col gap-1">
          <span className="text-[11px] text-muted-foreground">
            Wrote {artifactPaths.length}{" "}
            {artifactPaths.length === 1 ? "file" : "files"}
          </span>
          <div className="flex flex-wrap gap-2">
            {artifactPaths.map((p) => (
              <FileChip key={p} name={p} />
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
};

export default ToolPart;
