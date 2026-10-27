"use client";

import { useState } from "react";
import type { ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

export type GroupHeaderVariant = "band" | "plain";

/**
 * Linear-style list group header — a hatched band with an optional collapse
 * chevron, a small rounded-square color marker, the group label, and a count
 * pill. Shared by the Skills list and the Dashboard blockers panel so grouping
 * looks identical everywhere. The `plain` variant drops the band for a heading
 * that sits above its own table or grid (Automation, Connections).
 */
export function GroupHeader({
  label,
  count,
  color,
  icon,
  collapsed = false,
  onToggle,
  sticky = true,
  variant = "band",
  className,
}: {
  label: ReactNode;
  count?: number;
  /** CSS color for the marker (rounded square, or the `icon` when provided). */
  color?: string;
  /** Minimalist status icon drawn in `color`; replaces the square marker. */
  icon?: ReactNode;
  collapsed?: boolean;
  onToggle?: () => void;
  /** Stick to the top of the scroll container (default true; band only). */
  sticky?: boolean;
  variant?: GroupHeaderVariant;
  className?: string;
}) {
  const cls = cn(
    "flex h-9 w-full items-center gap-2 text-left",
    variant === "band"
      ? "skill-hatch border-b border-zinc-100 px-4 dark:border-zinc-800/70"
      : "px-1",
    variant === "band" && sticky && "sticky top-0 z-10",
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
      {icon ? (
        <span
          className={cn(
            "flex shrink-0 items-center justify-center [&>svg]:h-[14px] [&>svg]:w-[14px]",
            !color && variant === "plain" && "text-muted-foreground"
          )}
          style={{ color }}
        >
          {icon}
        </span>
      ) : color ? (
        <span
          className="h-[9px] w-[9px] shrink-0 rounded-[3px]"
          style={{ backgroundColor: color }}
        />
      ) : null}
      <span className="text-[12.5px] font-semibold">{label}</span>
      {count != null && (
        <span className="rounded-full bg-muted px-[7px] text-[11.5px] leading-[17px] text-muted-foreground">
          {count}
        </span>
      )}
    </>
  );

  return onToggle ? (
    <button
      type="button"
      aria-expanded={!collapsed}
      onClick={onToggle}
      className={cls}
    >
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
  icon,
  defaultOpen = true,
  sticky,
  variant,
  headerClassName,
  children,
}: {
  label: ReactNode;
  count?: number;
  color?: string;
  icon?: ReactNode;
  defaultOpen?: boolean;
  sticky?: boolean;
  variant?: GroupHeaderVariant;
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
        icon={icon}
        collapsed={!open}
        onToggle={() => setOpen((o) => !o)}
        sticky={sticky}
        variant={variant}
        className={headerClassName}
      />
      {open && children}
    </div>
  );
}
