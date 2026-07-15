import React, { useState } from "react";
import Image from "next/image";
import { useTranslations } from "next-intl";
import { ChevronDown, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import MessageWrapper from "./MessageWrapper";
import { ToolIcon } from "../utils/toolIcon";
import { describeToolCall, summarizeToolGroup } from "../utils/describeToolCall";
import { ToolCallGroupData } from "../types";

interface ToolCallGroupMessageProps {
  data: ToolCallGroupData;
}

const ToolCallGroupMessage: React.FC<ToolCallGroupMessageProps> = ({ data }) => {
  const t = useTranslations("Chat.Messages");
  const { tools } = data;

  const hasPending = tools.some((tool) => tool.pending);

  // Collapse a finished section by default (the way coding agents fold away
  // completed work); only keep it open while something is still running.
  const [isOpen, setIsOpen] = useState(hasPending);
  const [expandedTools, setExpandedTools] = useState<Set<string>>(new Set());

  const toggleTool = (toolCallId: string) => {
    setExpandedTools((prev) => {
      const next = new Set(prev);
      if (next.has(toolCallId)) {
        next.delete(toolCallId);
      } else {
        next.add(toolCallId);
      }
      return next;
    });
  };

  const completedCount = tools.filter((t) => !t.pending).length;
  const totalCount = tools.length;

  const summary = summarizeToolGroup(tools.map((tl) => tl.tool_name));
  const failedCount = tools.filter((tl) => !tl.pending && !tl.success).length;

  const allCallIds = tools.map((tl) => tl.tool_call_id).filter(Boolean);

  return (
    <MessageWrapper type="tool-result">
      <div
        id={allCallIds[0] ? `tc-${allCallIds[0]}` : undefined}
        data-aa-tc={allCallIds.join(" ")}
        className="w-full max-w-full scroll-mt-20 lg:max-w-[80%]"
      >
        {/* Summary header — plain, muted, no card. */}
        <button
          type="button"
          onClick={() => setIsOpen((v) => !v)}
          className="flex w-full items-center gap-1.5 py-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <span className="flex-1 truncate text-left">{summary}</span>
          {hasPending && (
            <span className="shrink-0 text-xs tabular-nums">
              {completedCount}/{totalCount}
            </span>
          )}
          {!hasPending && failedCount > 0 && (
            <span className="shrink-0 text-xs">{failedCount} failed</span>
          )}
          {isOpen ? (
            <ChevronDown className="h-3.5 w-3.5 shrink-0" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 shrink-0" />
          )}
        </button>

        {/* Tool list */}
        {isOpen && (
          <div className="mt-1 divide-y divide-border/60 rounded-lg border border-border/60">
            {tools.map((tool) => {
              const isExpanded = expandedTools.has(tool.tool_call_id);
              const hasResult = !tool.pending && tool.result != null;
              const hasArgs =
                tool.arguments && Object.keys(tool.arguments).length > 0;
              const desc = describeToolCall(tool.tool_name, tool.arguments);

              return (
                <div
                  key={tool.tool_call_id}
                  id={tool.tool_call_id ? `tc-${tool.tool_call_id}` : undefined}
                  className="scroll-mt-20 px-3 py-1.5"
                >
                  {/* Tool row */}
                  <button
                    type="button"
                    onClick={() =>
                      (hasResult || hasArgs) && toggleTool(tool.tool_call_id)
                    }
                    className={cn(
                      "flex w-full items-center gap-2 text-xs",
                      hasResult || hasArgs
                        ? "cursor-pointer hover:opacity-80"
                        : "cursor-default"
                    )}
                  >
                    {tool.server_icon ? (
                      <Image
                        src={tool.server_icon}
                        alt=""
                        width={14}
                        height={14}
                        className="h-3.5 w-3.5 shrink-0 rounded-sm object-contain"
                      />
                    ) : (
                      <ToolIcon
                        name={tool.tool_name}
                        className="h-3.5 w-3.5 shrink-0 text-muted-foreground"
                      />
                    )}
                    <span className="flex flex-1 items-center gap-1.5 text-left text-foreground">
                      <span className="font-medium">{desc.text}</span>
                      {desc.code && (
                        <code className="truncate rounded bg-black/5 px-1 py-0.5 font-mono text-[11px] text-muted-foreground dark:bg-white/10">
                          {desc.code}
                        </code>
                      )}
                    </span>
                    {!tool.pending && !tool.success && (
                      <span className="shrink-0 text-xs text-muted-foreground">
                        failed
                      </span>
                    )}
                    {tool.execution_time && (
                      <span className="shrink-0 text-xs text-muted-foreground">
                        {tool.execution_time}
                      </span>
                    )}
                    {tool.pending && (
                      <span className="shrink-0 animate-pulse text-xs text-muted-foreground">
                        {t("calling")}...
                      </span>
                    )}
                    {(hasResult || hasArgs) && (
                      isExpanded ? (
                        <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground" />
                      ) : (
                        <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground" />
                      )
                    )}
                  </button>

                  {/* Expanded details */}
                  {isExpanded && (
                    <div className="mt-1.5 space-y-1.5 pl-5">
                      {hasArgs && (
                        <div>
                          <div className="mb-0.5 text-xs text-muted-foreground">
                            Arguments
                          </div>
                          <pre className="overflow-x-auto rounded bg-black/5 p-1.5 text-xs text-foreground/80 dark:bg-white/5">
                            {JSON.stringify(tool.arguments, null, 2)}
                          </pre>
                        </div>
                      )}
                      {hasResult && (
                        <div>
                          <div className="mb-0.5 text-xs text-muted-foreground">
                            Result
                          </div>
                          <pre className="overflow-x-auto whitespace-pre-wrap rounded bg-black/5 p-1.5 text-xs text-foreground/80 dark:bg-white/5">
                            {typeof tool.result === "string"
                              ? tool.result
                              : JSON.stringify(tool.result, null, 2)}
                          </pre>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </MessageWrapper>
  );
};

export default ToolCallGroupMessage;
