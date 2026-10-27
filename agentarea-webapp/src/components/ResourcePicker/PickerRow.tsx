"use client";

import type { ComponentProps, ReactNode } from "react";
import { Loader2 } from "lucide-react";
import EmptyState from "@/components/EmptyState";
import { Checkbox } from "@/components/ui/checkbox";
import { EntityAvatar } from "@/components/ui/entity-avatar";
import { InteractiveListRow } from "@/components/ui/interactive-list-row";
import { Skeleton } from "@/components/ui/skeleton";

const SELECTED_TINT = "hsl(var(--primary))";

/** The shared empty state without its card — the sheet is the card here. */
export const PICKER_BARE_EMPTY_STATE =
  "border-0 bg-transparent p-6 shadow-none hover:bg-transparent dark:bg-transparent dark:hover:bg-transparent";

/** A picker's empty, failed or nothing-found state, centred in the list. */
export function PickerEmptyState(props: ComponentProps<typeof EmptyState>) {
  return (
    <div className="flex h-full flex-col justify-center">
      <EmptyState className={PICKER_BARE_EMPTY_STATE} {...props} />
    </div>
  );
}

/**
 * One row of a pick-several sheet: a soft tile, a title with a muted line
 * under it, and a checkbox. The whole row is the control — ticking attaches,
 * unticking detaches, and a picked row stays in the list, ticked.
 */
export function PickerRow({
  icon,
  iconScale = 0.45,
  title,
  subtitle,
  selected,
  pending = false,
  onToggle,
}: {
  /** What goes on the tile: a glyph, or a logo. */
  icon: ReactNode;
  /** How much of the tile the icon fills; a logo wants more than a glyph. */
  iconScale?: number;
  title: ReactNode;
  subtitle?: ReactNode;
  selected: boolean;
  /** Ticking started something that has not finished; the box waits for it. */
  pending?: boolean;
  onToggle: () => void;
}) {
  return (
    <InteractiveListRow
      onClick={pending ? undefined : onToggle}
      pressed={selected}
      showIndicator={false}
      dividerClassName=""
      className="px-5 py-2"
      start={
        <EntityAvatar
          variant="soft"
          size={32}
          color={selected ? SELECTED_TINT : undefined}
          iconScale={iconScale}
          icon={icon}
          aria-hidden
        />
      }
      end={
        pending ? (
          <Loader2
            aria-hidden
            className="h-4 w-4 animate-spin text-muted-foreground"
          />
        ) : (
          // The row is the control; the box only shows its state.
          <Checkbox
            checked={selected}
            tabIndex={-1}
            aria-hidden
            className="pointer-events-none border-zinc-300 dark:border-zinc-600 data-[state=checked]:border-primary data-[state=checked]:bg-primary data-[state=checked]:text-primary-foreground"
          />
        )
      }
    >
      <div className="min-w-0 flex-1">
        <p className="truncate text-[13px] font-medium leading-5 text-foreground">
          {title}
        </p>
        {subtitle ? (
          <p className="truncate text-xs leading-4 text-muted-foreground">
            {subtitle}
          </p>
        ) : null}
      </div>
    </InteractiveListRow>
  );
}

/** Stand-in for a picker list while it loads: the section label and its rows. */
export function PickerRowsSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div aria-hidden className="px-5">
      <Skeleton className="mb-2 mt-1.5 h-3 w-20" />
      {Array.from({ length: rows }).map((_, index) => (
        <div key={index} className="flex items-center gap-3 py-2">
          <Skeleton className="h-8 w-8 rounded-[9px]" />
          <div className="flex-1 space-y-1.5">
            <Skeleton className="h-3 w-2/5" />
            <Skeleton className="h-2.5 w-3/5" />
          </div>
          <Skeleton className="h-4 w-4 rounded-sm" />
        </div>
      ))}
    </div>
  );
}
