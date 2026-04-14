import React, { useState } from "react";
import { useTranslations } from "next-intl";
import { ChevronDown, ChevronRight, Wrench } from "lucide-react";
import { cn } from "@/lib/utils";
import MessageWrapper from "./MessageWrapper";
import { ToolCallGroupData } from "../types";

interface ToolCallGroupMessageProps {
  data: ToolCallGroupData;
}

const ToolCallGroupMessage: React.FC<ToolCallGroupMessageProps> = ({ data }) => {
  const t = useTranslations("Chat.Messages");
  const { tools } = data;

  const hasFailure = tools.some((tool) => !tool.pending && !tool.success);
  const hasPending = tools.some((tool) => tool.pending);

  // Collapsed by default when all succeeded; expanded if any failed or pending
  const [isOpen, setIsOpen] = useState(hasFailure || hasPending);
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

  const headerLabel = hasPending
    ? t("toolCallGroupRunning", { count: totalCount })
    : t("toolCallGroup", { count: totalCount });

  return (
    <MessageWrapper type="tool-result">
      <div className="w-full max-w-full lg:max-w-[80%]">
        <div
          className={cn(
            "w-full rounded-lg border dark:border-zinc-700",
            hasFailure
              ? "bg-red-50 dark:bg-red-950/30 border-red-200 dark:border-red-800"
              : hasPending
                ? "bg-blue-50 dark:bg-blue-950/30 border-blue-200 dark:border-blue-800"
                : "bg-green-50 dark:bg-green-950/30 border-green-200 dark:border-green-800"
          )}
        >
          {/* Group header */}
          <button
            type="button"
            onClick={() => setIsOpen((v) => !v)}
            className="flex w-full items-center gap-2 px-3 py-2 text-sm hover:opacity-80 transition-opacity"
          >
            <Wrench
              className={cn(
                "h-3.5 w-3.5 shrink-0",
                hasFailure
                  ? "text-red-500"
                  : hasPending
                    ? "text-blue-500 animate-pulse"
                    : "text-green-500"
              )}
            />
            <span
              className={cn(
                "flex-1 text-left font-medium",
                hasFailure
                  ? "text-red-700 dark:text-red-300"
                  : hasPending
                    ? "text-blue-700 dark:text-blue-300"
                    : "text-green-700 dark:text-green-300"
              )}
            >
              {headerLabel}
            </span>
            {hasPending && (
              <span className="text-xs text-blue-500 dark:text-blue-400">
                {completedCount}/{totalCount}
              </span>
            )}
            {isOpen ? (
              <ChevronDown className="h-3.5 w-3.5 text-gray-400 shrink-0" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5 text-gray-400 shrink-0" />
            )}
          </button>

          {/* Tool list */}
          {isOpen && (
            <div className="border-t dark:border-zinc-700 divide-y divide-current/10">
              {tools.map((tool) => {
                const isExpanded = expandedTools.has(tool.tool_call_id);
                const hasResult = !tool.pending && tool.result != null;
                const hasArgs =
                  tool.arguments && Object.keys(tool.arguments).length > 0;

                return (
                  <div key={tool.tool_call_id} className="px-3 py-1.5">
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
                      <span
                        className={cn(
                          "flex-1 text-left font-mono",
                          tool.pending
                            ? "text-blue-600 dark:text-blue-400"
                            : !tool.success
                              ? "text-red-600 dark:text-red-400"
                              : "text-green-700 dark:text-green-300"
                        )}
                      >
                        {tool.tool_name}
                      </span>
                      {tool.execution_time && (
                        <span className="text-gray-400 text-xs shrink-0">
                          {tool.execution_time}
                        </span>
                      )}
                      {tool.pending && (
                        <span className="text-blue-500 animate-pulse text-xs shrink-0">
                          {t("calling")}...
                        </span>
                      )}
                      {(hasResult || hasArgs) && (
                        isExpanded ? (
                          <ChevronDown className="h-3 w-3 text-gray-400 shrink-0" />
                        ) : (
                          <ChevronRight className="h-3 w-3 text-gray-400 shrink-0" />
                        )
                      )}
                    </button>

                    {/* Expanded details */}
                    {isExpanded && (
                      <div className="mt-1.5 space-y-1.5 pl-5">
                        {hasArgs && (
                          <div>
                            <div className="text-xs text-gray-500 dark:text-gray-400 mb-0.5">
                              Arguments
                            </div>
                            <pre className="overflow-x-auto rounded bg-black/5 dark:bg-white/5 p-1.5 text-xs text-gray-700 dark:text-gray-300">
                              {JSON.stringify(tool.arguments, null, 2)}
                            </pre>
                          </div>
                        )}
                        {hasResult && (
                          <div>
                            <div className="text-xs text-gray-500 dark:text-gray-400 mb-0.5">
                              Result
                            </div>
                            <pre className="overflow-x-auto rounded bg-black/5 dark:bg-white/5 p-1.5 text-xs text-gray-700 dark:text-gray-300 whitespace-pre-wrap">
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
      </div>
    </MessageWrapper>
  );
};

export default ToolCallGroupMessage;
