"use client";

import type { ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

function Inner({
  icon,
  name,
  count,
  sub,
}: {
  icon: ReactNode;
  name: string;
  count: number;
  sub?: string;
}) {
  return (
    <>
      <span className="grid h-[18px] w-[18px] shrink-0 place-items-center rounded-[5px] bg-primary/10 text-primary">
        {icon}
      </span>
      <span className="text-[12.5px] font-semibold text-foreground">{name}</span>
      <span className="rounded-full bg-muted px-[7px] text-[11.5px] leading-[17px] text-muted-foreground">
        {count}
      </span>
      {sub != null && (
        <span className="collection-section-sub truncate text-[11.5px] font-normal text-muted-foreground/70">
          {sub}
        </span>
      )}
    </>
  );
}

/**
 * The shared section header for multi-section collection pages (Connections,
 * Models, …): a tinted icon + name + count badge + muted sub-label. In list
 * view it's a sticky, hatched, collapsible bar; in grid view it's a plain
 * header (no chevron / hatch). The `sub` text auto-hides on xs screens.
 */
export default function CollectionSectionHeader({
  icon,
  name,
  count,
  sub,
  variant,
  collapsed,
  onToggle,
}: {
  icon: ReactNode;
  name: string;
  count: number;
  sub?: string;
  variant: "list" | "grid";
  collapsed?: boolean;
  onToggle?: () => void;
}) {
  if (variant === "grid") {
    return (
      <div className="flex items-center gap-2 px-4 pb-2.5 pt-5">
        <Inner icon={icon} name={name} count={count} sub={sub} />
      </div>
    );
  }
  return (
    <button
      type="button"
      onClick={onToggle}
      className="collection-hatch sticky top-0 z-[3] flex h-9 w-full items-center gap-2 border-b border-t border-zinc-100 px-4 first:border-t-0 dark:border-zinc-800/70"
    >
      <ChevronDown
        className={cn(
          "h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform",
          collapsed && "-rotate-90"
        )}
      />
      <Inner icon={icon} name={name} count={count} sub={sub} />
    </button>
  );
}
