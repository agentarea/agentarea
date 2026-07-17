"use client";

import { createElement } from "react";
import Image from "next/image";
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
        <Image
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

// Just the glyph (no circle), for inline icon+label chips.
function ToolGlyph({ tool }: { tool: AgentToolIcon }) {
  if (tool.kind === "builtin") {
    const icon = getBuiltinToolIcon(tool.toolName);
    return createElement(icon, {
      className: "h-3.5 w-3.5 shrink-0 text-muted-foreground",
    });
  }
  if (tool.src) {
    return (
      <Image
        src={tool.src}
        alt={tool.label}
        width={14}
        height={14}
        className="h-3.5 w-3.5 shrink-0 rounded-sm object-contain"
      />
    );
  }
  const unresolved = tool.kind === "mcp" && !tool.resolved;
  const fallbackIcon = tool.kind === "openapi" ? Globe : Plug;
  return createElement(fallbackIcon, {
    className: cn(
      "h-3.5 w-3.5 shrink-0 text-muted-foreground",
      unresolved && "opacity-40"
    ),
  });
}

/** Icon + label chips — for detail views where tool names should be visible. */
export function AgentToolPills({
  tools,
  className,
}: {
  tools: AgentToolIcon[];
  className?: string;
}) {
  if (!tools.length) return null;
  return (
    <div className={cn("flex flex-wrap gap-1.5", className)}>
      {tools.map((tool, index) => {
        const unresolved = tool.kind === "mcp" && !tool.resolved;
        return (
          <span
            key={index}
            title={unresolved ? `${tool.label} (not connected)` : tool.label}
            className={cn(
              "inline-flex min-w-0 items-center gap-1.5 rounded-full border border-border bg-muted/40 px-2 py-0.5 text-[11.5px] text-foreground/80",
              unresolved && "border-dashed opacity-60"
            )}
          >
            <ToolGlyph tool={tool} />
            <span className="max-w-[150px] truncate">{tool.label}</span>
          </span>
        );
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
