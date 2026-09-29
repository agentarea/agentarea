"use client";

import { createElement } from "react";
import Image from "next/image";
import { Globe, Plug } from "lucide-react";
import { getBuiltinToolIcon } from "@/app/w/[workspace]/(main)/agents/create/utils/builtinToolUtils";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import { cn } from "@/lib/utils";
import { AgentToolIcon } from "@/utils/agentToolIcons";

type AgentToolIconsProps = {
  tools: AgentToolIcon[];
  maxDisplay?: number;
  className?: string;
};

const CIRCLE =
  "flex h-6 w-6 items-center justify-center overflow-hidden rounded-full border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900";

const INITIALS_MARK =
  "grid h-full w-full place-items-center bg-zinc-900 text-[8px] font-semibold leading-none text-white dark:bg-zinc-100 dark:text-zinc-950";

/** A ref that resolved to nothing — the runtime skips it, so say so. */
function isUnresolved(tool: AgentToolIcon): boolean {
  return (
    (tool.kind === "mcp" || tool.kind === "openapi") && !tool.resolved
  );
}

function toolTitle(tool: AgentToolIcon): string {
  return isUnresolved(tool) ? `${tool.label} (not connected)` : tool.label;
}

function ToolChip({ tool }: { tool: AgentToolIcon }) {
  if (tool.kind === "builtin") {
    const icon = getBuiltinToolIcon(tool.toolName);
    return (
      <div className={CIRCLE} title={tool.label}>
        {createElement(icon, { className: "h-3.5 w-3.5 text-muted-foreground" })}
      </div>
    );
  }

  if (tool.kind === "mcp" && tool.src) {
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

  // OpenAPI connections carry no logo, so the domain initials are their mark —
  // the same identity the /connections page shows.
  if (tool.kind === "openapi" && tool.initials) {
    return (
      <div className={CIRCLE} title={tool.label}>
        <span className={INITIALS_MARK}>{tool.initials}</span>
      </div>
    );
  }

  const unresolved = isUnresolved(tool);
  return (
    <div
      className={cn(CIRCLE, unresolved && "border-dashed opacity-40")}
      title={toolTitle(tool)}
    >
      {createElement(fallbackIcon(tool), {
        className: "h-3.5 w-3.5 text-muted-foreground",
      })}
    </div>
  );
}

function fallbackIcon(tool: AgentToolIcon) {
  if (tool.kind === "openapi") return Globe;
  if (tool.kind === "agent") return ENTITY_ICONS.agent;
  return Plug;
}

// Just the glyph (no circle), for inline icon+label chips.
function ToolGlyph({ tool }: { tool: AgentToolIcon }) {
  if (tool.kind === "builtin") {
    const icon = getBuiltinToolIcon(tool.toolName);
    return createElement(icon, {
      className: "h-3.5 w-3.5 shrink-0 text-muted-foreground",
    });
  }
  if (tool.kind === "mcp" && tool.src) {
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
  if (tool.kind === "openapi" && tool.initials) {
    return (
      <span
        className={cn(
          INITIALS_MARK,
          "h-3.5 w-3.5 shrink-0 rounded-sm text-[7px]"
        )}
      >
        {tool.initials}
      </span>
    );
  }
  return createElement(fallbackIcon(tool), {
    className: cn(
      "h-3.5 w-3.5 shrink-0 text-muted-foreground",
      isUnresolved(tool) && "opacity-40"
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
      {tools.map((tool, index) => (
        <span
          key={index}
          title={toolTitle(tool)}
          className={cn(
            "inline-flex min-w-0 items-center gap-1.5 rounded-full border border-border bg-muted/40 px-2 py-0.5 text-[11.5px] text-foreground/80",
            isUnresolved(tool) && "border-dashed opacity-60"
          )}
        >
          <ToolGlyph tool={tool} />
          <span className="max-w-[150px] truncate">{tool.label}</span>
        </span>
      ))}
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
