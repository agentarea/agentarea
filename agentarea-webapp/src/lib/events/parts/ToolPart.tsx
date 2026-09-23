"use client";

import React from "react";
import { Check, ChevronRight, Copy, Loader2 } from "lucide-react";
import { MessageMarkdown } from "@/components/Chat/MessageMarkdown";
import {
  describeToolCall,
  type ToolMeta,
} from "@/components/Chat/utils/describeToolCall";
import {
  FileChip,
  fileBasename,
} from "@/components/Chat/utils/fileIcon";
import { SiteLink } from "@/components/Chat/utils/SiteLink";
import { ToolIcon } from "@/components/Chat/utils/toolIcon";
import {
  containsUnavailableToolValue,
  hasAvailableToolValue,
  isUnavailableToolValue,
  stripUnavailableToolValues,
  TOOL_DETAILS_UNAVAILABLE,
} from "@/components/Chat/utils/toolDetails";
import type { Part } from "../contract";

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

function formatValue(value: unknown): string {
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2) ?? String(value);
  } catch {
    return String(value);
  }
}

function pickString(
  value: Record<string, unknown> | undefined,
  keys: string[]
): string | undefined {
  for (const key of keys) {
    const item = value?.[key];
    if (
      typeof item === "string" &&
      item.trim() &&
      !isUnavailableToolValue(item)
    ) {
      return item;
    }
  }
  return undefined;
}

function isShellTool(toolName: string, command?: string): boolean {
  return (
    Boolean(command) &&
    /(shell|bash|terminal|command|cmd|execute|exec|run_|script)/i.test(toolName)
  );
}

function compactUrl(url: string): string {
  try {
    const parsed = new URL(url);
    return `${parsed.hostname}${parsed.pathname === "/" ? "" : parsed.pathname}`;
  } catch {
    return url;
  }
}

function CopyToolDetailsButton({ value }: { value: string }) {
  const [copied, setCopied] = React.useState(false);
  const copy = async () => {
    if (!navigator.clipboard?.writeText) return;
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      // The browser keeps clipboard failures non-destructive; details remain visible.
    }
  };

  return (
    <button
      type="button"
      onClick={copy}
      aria-label="Copy tool details"
      title={copied ? "Copied" : "Copy tool details"}
      className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
    </button>
  );
}

/** Compact tool row with an accessible disclosure for real arguments/results. */
export const ToolPart: React.FC<{
  part: Part;
  onInspect?: () => void;
  suppressUnavailableDetails?: boolean;
}> = ({ part, onInspect, suppressUnavailableDetails = false }) => {
  const data = part.data;
  const toolName =
    (typeof data.tool_name === "string" && data.tool_name) ||
    (typeof data.name === "string" && data.name) ||
    "tool";
  const args = asRecord(data.arguments) ?? asRecord(data.args);
  const exitCode = typeof data.exit_code === "number" ? data.exit_code : null;
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
  const explicitFailure =
    exitCode == null ? data.success === false : exitCode !== 0;
  const rawResult = data.result;
  const resultAvailable = hasAvailableToolValue(rawResult);
  const result = resultAvailable
    ? stripUnavailableToolValues(rawResult)
    : undefined;
  const rawError =
    typeof data.error === "string"
      ? data.error
      : typeof data.message === "string" && explicitFailure
        ? data.message
        : null;
  const errorAvailable = hasAvailableToolValue(rawError);
  const error = errorAvailable ? rawError : null;
  const failed = !inFlight && (explicitFailure || errorAvailable);
  const succeeded =
    !inFlight && !failed && (exitCode === 0 || data.success === true);
  const displayArgs = stripUnavailableToolValues(args);
  const displayArgsRecord =
    displayArgs && typeof displayArgs === "object"
      ? (displayArgs as Record<string, unknown>)
      : undefined;
  const artifactPaths = asStringArray(data.artifact_paths);
  const hasArguments = Boolean(
    displayArgsRecord && Object.keys(displayArgsRecord).length > 0
  );
  const hasOutput = resultAvailable;
  const unavailableDetails =
    (rawResult !== undefined &&
      rawResult !== null &&
      containsUnavailableToolValue(rawResult)) ||
    (rawError !== null && containsUnavailableToolValue(rawError)) ||
    (args !== undefined && containsUnavailableToolValue(args));
  const hasExpandableDetails = hasArguments || hasOutput || Boolean(error);
  const showUnavailableDetails =
    unavailableDetails && !suppressUnavailableDetails;
  const duration =
    typeof data.duration_ms === "number" && Number.isFinite(data.duration_ms)
      ? `${data.duration_ms} ms`
      : typeof data.execution_time === "number" &&
          Number.isFinite(data.execution_time)
        ? `${data.execution_time} s`
        : typeof data.execution_time === "string" &&
            data.execution_time.trim() &&
            !isUnavailableToolValue(data.execution_time)
          ? data.execution_time.trim()
          : null;
  const statusMetadata = [
    exitCode !== null ? `exit ${exitCode}` : null,
    duration,
  ]
    .filter(Boolean)
    .join(" · ");
  const command = pickString(displayArgsRecord, [
    "command",
    "cmd",
    "script",
    "code",
  ]);
  const shellTool = isShellTool(toolName, command);
  const toolIconUrl = pickString(data, [
    "server_icon",
    "mcp_server_icon",
    "server_icon_url",
    "icon_url",
  ]);
  const fileTarget = /(read|write|edit|patch|file|document|list|glob)/i.test(
    toolName
  )
    ? pickString(displayArgsRecord, ["path", "file", "filename", "file_path"])
    : undefined;
  const urlTarget = pickString(displayArgsRecord, ["url", "href", "uri", "link"]);
  const reachableUrl =
    urlTarget && /^(https?:\/\/|\/)/i.test(urlTarget) ? urlTarget : undefined;
  const queryTarget = pickString(displayArgsRecord, [
    "query",
    "q",
    "search",
    "text",
  ]);
  const serviceName = pickString(data, [
    "server_name",
    "mcp_server_name",
    "integration_name",
  ]);
  const fileLabel = fileTarget ? fileBasename(fileTarget) : undefined;
  const actionVerb = fileLabel && text.endsWith(fileLabel)
    ? text.slice(0, -fileLabel.length).trim()
    : reachableUrl && /^(fetch|browse|open)/i.test(text)
      ? text.split(" ")[0]
      : text;
  const hasSummarySubject = Boolean(
    fileTarget || reachableUrl || code || queryTarget || serviceName
  );
  const shellParameters =
    shellTool && displayArgsRecord
      ? Object.fromEntries(
          Object.entries(displayArgsRecord).filter(
            ([key]) => !["command", "cmd", "script", "code"].includes(key)
          )
        )
      : undefined;
  const hasShellParameters = Boolean(
    shellParameters && Object.keys(shellParameters).length > 0
  );
  const copyText = [
    command
      ? `$ ${command}${hasShellParameters ? `\n\n${formatValue(shellParameters)}` : ""}`
      : hasArguments
        ? formatValue(displayArgsRecord)
        : null,
    hasOutput ? formatValue(result) : null,
    error ? `Error\n${error}` : null,
  ]
    .filter((value): value is string => Boolean(value))
    .join("\n\n");
  const completionLabel = inFlight
    ? "Running"
    : failed
      ? "Failed"
      : succeeded
        ? "Success"
        : "Completed";
  const statusLabel = inFlight
    ? `${text} · running`
    : failed
      ? `${text} · failed`
      : `${text} · done`;

  return (
    <div className="flex min-w-0 flex-col gap-1 text-[13px] leading-[21px]">
      {hasExpandableDetails ? (
        <details
          className="group/tool min-w-0"
          onToggle={(event) => {
            if (event.currentTarget.open) onInspect?.();
          }}
        >
          <summary
            aria-label={statusLabel}
            className="flex min-w-0 cursor-pointer list-none items-center gap-2 rounded-md px-1.5 py-1 outline-none hover:bg-muted/50 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset [&::-webkit-details-marker]:hidden"
          >
            <ToolIcon
              name={toolName}
              iconUrl={toolIconUrl}
              className="h-3.5 w-3.5 shrink-0 text-muted-foreground"
            />
            <span
              className={
                hasSummarySubject
                  ? "shrink-0 text-muted-foreground"
                  : "min-w-0 truncate font-medium text-foreground/80"
              }
            >
              {actionVerb}
            </span>
            {fileTarget ? (
              <FileChip
                name={fileLabel ?? fileTarget}
                iconName={fileTarget}
                className="min-w-0 font-medium text-foreground/85"
              />
            ) : reachableUrl ? (
              <span
                title={reachableUrl}
                className="min-w-0 truncate font-medium text-foreground/85"
              >
                {compactUrl(reachableUrl)}
              </span>
            ) : code ? (
              <code
                title={command ?? code}
                className="min-w-0 truncate font-mono text-[12px] font-medium text-foreground/80"
              >
                {code}
              </code>
            ) : serviceName && !text.includes(serviceName) ? (
              <span className="min-w-0 truncate font-medium text-foreground/85">
                {serviceName}
              </span>
            ) : null}
            {inFlight && <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-muted-foreground motion-reduce:animate-none" />}
            <ChevronRight
              aria-hidden
              className="ml-auto h-3 w-3 shrink-0 text-muted-foreground transition-transform motion-reduce:transition-none group-open/tool:rotate-90"
            />
          </summary>
          <div className="mt-1 overflow-hidden rounded-xl border border-border bg-muted/25">
            <div className="flex items-center justify-between gap-3 px-3 py-1.5">
              <span className="font-medium text-foreground/75">
                {shellTool ? "Shell" : "Tool details"}
              </span>
              {copyText && <CopyToolDetailsButton value={copyText} />}
            </div>
            {shellTool && command ? (
              <>
                <pre className="max-h-40 overflow-auto border-t border-border/70 bg-background/70 px-3 py-2 font-mono text-[12px] leading-5 text-foreground [overflow-wrap:normal]">
                  <code className="whitespace-pre">$ {command}</code>
                </pre>
                {hasShellParameters && (
                  <pre className="max-h-32 overflow-auto border-t border-border/70 px-3 py-2 font-mono text-[12px] leading-5 text-muted-foreground [overflow-wrap:normal]">
                    <code className="whitespace-pre">
                      {formatValue(shellParameters)}
                    </code>
                  </pre>
                )}
              </>
            ) : hasArguments ? (
              <pre className="max-h-48 overflow-auto border-t border-border/70 bg-background/70 px-3 py-2 font-mono text-[12px] leading-5 text-foreground [overflow-wrap:normal]">
                <code className="whitespace-pre">
                  {formatValue(displayArgsRecord)}
                </code>
              </pre>
            ) : null}
            {reachableUrl && (
              <div className="border-t border-border/70 px-3 py-2">
                <SiteLink href={reachableUrl}>{reachableUrl}</SiteLink>
              </div>
            )}
            {showUnavailableDetails && (
              <p className="border-t border-border/70 px-3 py-2 text-muted-foreground">
                {TOOL_DETAILS_UNAVAILABLE}
              </p>
            )}
            {hasOutput && (
              <div className="max-h-64 overflow-auto border-t border-border/70 bg-background/70 px-3 py-2">
                {shellTool ? (
                  <pre className="min-w-max whitespace-pre font-mono text-[12px] leading-5 text-foreground">
                    {formatValue(result)}
                  </pre>
                ) : typeof result === "string" ? (
                  <MessageMarkdown content={result} />
                ) : (
                  <pre className="min-w-max whitespace-pre font-mono text-[12px] leading-5 text-foreground">
                    {formatValue(result)}
                  </pre>
                )}
              </div>
            )}
            {error && (
              <pre className="max-h-48 overflow-auto whitespace-pre border-t border-border/70 bg-background/70 px-3 py-2 font-mono text-[12px] leading-5 text-red-600 dark:text-red-400">
                {error}
              </pre>
            )}
            <div className="flex items-center justify-end gap-2 border-t border-border/70 px-3 py-1.5 text-[12px] text-muted-foreground">
              <span className={failed ? "text-red-600 dark:text-red-400" : ""}>
                {completionLabel}
              </span>
              {statusMetadata && <span>{statusMetadata}</span>}
            </div>
          </div>
        </details>
      ) : (
        <>
          <div
            aria-label={statusLabel}
            className="flex min-w-0 items-center gap-2 px-1.5 py-1"
          >
            <ToolIcon
              name={toolName}
              iconUrl={toolIconUrl}
              className="h-3.5 w-3.5 shrink-0 text-muted-foreground"
            />
            <span
              className={
                hasSummarySubject
                  ? "truncate text-muted-foreground"
                  : "min-w-0 truncate font-medium text-foreground/80"
              }
            >
              {actionVerb}
            </span>
            {fileTarget ? (
              <FileChip
                name={fileLabel ?? fileTarget}
                iconName={fileTarget}
                className="min-w-0 font-medium text-foreground/85"
              />
            ) : reachableUrl ? (
              <span
                title={reachableUrl}
                className="min-w-0 truncate font-medium text-foreground/85"
              >
                {compactUrl(reachableUrl)}
              </span>
            ) : queryTarget ? (
              <span className="min-w-0 truncate font-medium text-foreground/85">
                {queryTarget}
              </span>
            ) : serviceName && !text.includes(serviceName) ? (
              <span className="min-w-0 truncate font-medium text-foreground/85">
                {serviceName}
              </span>
            ) : null}
            {statusMetadata && (
              <span className="shrink-0 text-muted-foreground">
                {statusMetadata}
              </span>
            )}
            {failed && (
              <span className="text-red-600 dark:text-red-400">Failed</span>
            )}
            {inFlight && <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-muted-foreground motion-reduce:animate-none" />}
          </div>
          {showUnavailableDetails ? (
            <p className="px-1 text-[11px] text-muted-foreground">
              {TOOL_DETAILS_UNAVAILABLE}
            </p>
          ) : null}
        </>
      )}
      {artifactPaths.length > 0 ? (
        <div className="flex flex-col gap-1 px-3 pb-2">
          <span className="text-[11px] text-muted-foreground">
            Wrote {artifactPaths.length}{" "}
            {artifactPaths.length === 1 ? "file" : "files"}
          </span>
          <div className="flex flex-wrap gap-2">
            {artifactPaths.map((path) => (
              <FileChip key={path} name={path} />
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
};

export default ToolPart;
