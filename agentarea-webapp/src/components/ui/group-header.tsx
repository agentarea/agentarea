"use client";

import { useState } from "react";
import type { ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Linear-style list group header — a hatched band with an optional collapse
 * chevron, a small rounded-square color marker, the group label, and a count
 * pill. Shared by the Skills list and the Dashboard blockers panel so grouping
 * looks identical everywhere.
 */
export function GroupHeader({
  label,
  count,
  color,
  collapsed = false,
  onToggle,
  sticky = true,
  className,
}: {
  label: ReactNode;
  count?: number;
  /** CSS color for the rounded-square marker. Omit to hide the marker. */
  color?: string;
  collapsed?: boolean;
  onToggle?: () => void;
  /** Stick to the top of the scroll container (default true). */
  sticky?: boolean;
  className?: string;
}) {
  const cls = cn(
    "skill-hatch flex h-9 w-full items-center gap-2 border-b border-zinc-100 px-4 dark:border-zinc-800/70",
    sticky && "sticky top-0 z-[2]",
    className
  );
  const inner = (
    <>
      {onToggle && (
        <ChevronDown
          className={cn(
            "h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform",
            collapsed && "-rotate-90"
          )}
        />
      )}
      {color && (
        <span
          className="h-[9px] w-[9px] shrink-0 rounded-[3px]"
          style={{ backgroundColor: color }}
        />
      )}
      <span className="text-[12.5px] font-semibold">{label}</span>
      {count != null && (
        <span className="rounded-full bg-muted px-[7px] text-[11.5px] leading-[17px] text-muted-foreground">
          {count}
        </span>
      )}
    </>
  );

  return onToggle ? (
    <button type="button" onClick={onToggle} className={cls}>
      {inner}
    </button>
  ) : (
    <div className={cls}>{inner}</div>
  );
}

/**
 * A group whose rows can be collapsed under a {@link GroupHeader}. Keeps the
 * open/closed state client-side while its children (rows) can be rendered on
 * the server and passed in — so any per-row timestamps are computed once and
 * don't cause hydration drift.
 */
export function CollapsibleGroup({
  label,
  count,
  color,
  defaultOpen = true,
  sticky,
  headerClassName,
  children,
}: {
  label: ReactNode;
  count?: number;
  color?: string;
  defaultOpen?: boolean;
  sticky?: boolean;
  headerClassName?: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div>
      <GroupHeader
        label={label}
        count={count}
        color={color}
        collapsed={!open}
        onToggle={() => setOpen((o) => !o)}
        sticky={sticky}
        className={headerClassName}
      />
      {open && children}
    </div>
  );
}
