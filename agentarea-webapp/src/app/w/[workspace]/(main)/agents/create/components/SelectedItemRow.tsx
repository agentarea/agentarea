"use client";

import type { ReactNode } from "react";
import { ChevronDown, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { InteractiveListRow } from "@/components/ui/interactive-list-row";
import { cn } from "@/lib/utils";

/** The rows a form section has picked, in one bordered block, or its note. */
export function SelectedItems({
  count,
  empty,
  children,
}: {
  count: number;
  /** What the section says while nothing is picked. */
  empty: ReactNode;
  children: ReactNode;
}) {
  if (!count) {
    return (
      // A dashed line in the list's place, like an empty list in the policy
      // editor: it says nothing is here without standing in for a card.
      <p className="rounded-md border border-dashed border-border/70 px-3 py-2 text-xs text-muted-foreground dark:border-zinc-700">
        {empty}
      </p>
    );
  }
  return (
    <div className="overflow-hidden rounded-md border dark:border-zinc-700">
      {children}
    </div>
  );
}

/**
 * A picked item in a form section: its avatar, its name with a muted line on
 * the same line, and a bin on hover. With `children` the row opens to show
 * them under the name; without, it only reads and removes.
 */
export function SelectedItemRow({
  avatar,
  title,
  badge,
  subtitle,
  end,
  removeLabel,
  onRemove,
  actions,
  actionCount = 0,
  open = false,
  onOpenChange,
  stacked = false,
  children,
}: {
  /** A 24px tile or avatar. */
  avatar: ReactNode;
  title: ReactNode;
  /** A kind marker after the name, e.g. "A2A". */
  badge?: ReactNode;
  subtitle?: ReactNode;
  /** Quiet state at the right edge, e.g. "3/5"; the actions take its place on hover. */
  end?: ReactNode;
  removeLabel?: string;
  /** Absent for a row that stays, like a toolset group. */
  onRemove?: () => void;
  /** More buttons before the bin, e.g. edit. */
  actions?: ReactNode;
  /** How many buttons `actions` holds, so the name leaves them room. */
  actionCount?: number;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** The muted line under the name, in full, for a setting that needs its why. */
  stacked?: boolean;
  children?: ReactNode;
}) {
  const expandable = Boolean(children) && Boolean(onOpenChange);
  const buttons = actionCount + (onRemove ? 1 : 0);

  return (
    <div
      // An open row reads as one block: the row and what it shows share a
      // tint, apart from the rows around it.
      className={cn(
        "border-b last:border-b-0 dark:border-zinc-700",
        open && children && "bg-muted/40 dark:bg-zinc-700/20"
      )}
    >
      <InteractiveListRow
        onClick={expandable ? () => onOpenChange?.(!open) : undefined}
        selected={open}
        pressed={expandable ? open : undefined}
        className="px-3 py-2"
        selectedClassName=""
        dividerClassName=""
        start={avatar}
        end={end}
        // The row stays open-looking while what it holds is shown.
        forceHoverActionsVisible={open}
        showIndicator={expandable}
        indicator={
          <ChevronDown
            className={cn(
              "h-4 w-4 text-muted-foreground transition-transform",
              open && "rotate-180"
            )}
          />
        }
        // 28px a button, 2px between, past the chevron when there is one.
        hoverActionsWidth={(expandable ? 48 : 16) + 30 * buttons - 2}
        hoverActionsClassName={expandable ? undefined : "right-2"}
        hoverActions={
          buttons ? (
            <>
              {actions}
              {onRemove && (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  onClick={onRemove}
                  className="h-7 w-7 text-muted-foreground hover:bg-destructive/10 hover:text-destructive dark:hover:bg-red-500/15 dark:hover:text-red-200"
                  aria-label={removeLabel}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              )}
            </>
          ) : undefined
        }
      >
        {stacked ? (
          <div className="min-w-0 flex-1">
            <div className="flex items-baseline gap-2">
              <span className="text-[13px] font-medium leading-5">{title}</span>
              {badge}
            </div>
            {subtitle ? (
              <p className="text-xs leading-4 text-muted-foreground">
                {subtitle}
              </p>
            ) : null}
          </div>
        ) : (
          <div className="flex min-w-0 flex-1 items-baseline gap-2">
            <span className="shrink-0 text-[13px] font-medium leading-5">
              {title}
            </span>
            {badge}
            {subtitle ? (
              <span className="truncate text-xs text-muted-foreground">
                {subtitle}
              </span>
            ) : null}
          </div>
        )}
      </InteractiveListRow>
      {expandable && open && (
        // Under the name, past the avatar (12px pad + 24px + 12px gap).
        <div className="space-y-4 pb-4 pl-12 pr-3 pt-1">{children}</div>
      )}
    </div>
  );
}
