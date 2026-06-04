"use client";

import { createElement } from "react";
import { Globe, Plug } from "lucide-react";
import { getBuiltinToolIcon } from "@/app/(main)/agents/create/utils/builtinToolUtils";
import { cn } from "@/lib/utils";
import { AgentToolIcon } from "@/utils/agentToolIcons";

type AgentToolIconsProps = {
  tools: AgentToolIcon[];
  maxDisplay?: number;
  className?: string;
};

const CIRCLE =
  "flex h-6 w-6 items-center justify-center overflow-hidden rounded-full border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900";

function ToolChip({ tool }: { tool: AgentToolIcon }) {
  if (tool.kind === "builtin") {
    const icon = getBuiltinToolIcon(tool.toolName);
    return (
      <div className={CIRCLE} title={tool.label}>
        {createElement(icon, { className: "h-3.5 w-3.5 text-muted-foreground" })}
      </div>
    );
  }

  if (tool.src) {
    return (
      <div className={CIRCLE} title={tool.label}>
        <img
          src={tool.src}
          alt={tool.label}
          width={24}
          height={24}
          className="h-full w-full object-contain"
        />
      </div>
    );
  }

  // An MCP ref that resolved to no instance/server is dangling — the runtime
  // skips it. Render it muted + dashed so it reads as "not connected".
  const unresolved = tool.kind === "mcp" && !tool.resolved;
  const fallbackIcon = tool.kind === "openapi" ? Globe : Plug;
  return (
    <div
      className={cn(CIRCLE, unresolved && "border-dashed opacity-40")}
      title={unresolved ? `${tool.label} (not connected)` : tool.label}
    >
      {createElement(fallbackIcon, {
        className: "h-3.5 w-3.5 text-muted-foreground",
      })}
    </div>
  );
}

export function AgentToolIcons({
  tools,
  maxDisplay = 5,
  className,
}: AgentToolIconsProps) {
  if (!tools.length) return null;

  const shown = tools.slice(0, maxDisplay);
  const extra = tools.length - shown.length;

  return (
    <div className={cn("z-10 flex -space-x-1.5 rtl:space-x-reverse", className)}>
      {shown.map((tool, index) => (
        <ToolChip key={index} tool={tool} />
      ))}
      {extra > 0 && (
        <div className="flex h-6 w-6 items-center justify-center rounded-full border border-zinc-200 bg-white text-center text-xs font-light text-zinc-400 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-200">
          +{extra}
        </div>
      )}
    </div>
  );
}
