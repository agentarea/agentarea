"use client";

import {
  CountSegmentedControl,
  type CountSegmentedControlProps,
} from "@/components/ui/count-segmented-control";
import { cn } from "@/lib/utils";

export type SegmentedControlProps<T extends string = string> =
  CountSegmentedControlProps<T>;

/**
 * A framed mode switch built on the shared animated segmented control.
 * Use it when the options are one compact control rather than page navigation.
 */
export function SegmentedControl<T extends string = string>({
  variant = "solid",
  className,
  itemClassName,
  activePillClassName,
  ...props
}: SegmentedControlProps<T>) {
  return (
    <CountSegmentedControl
      {...props}
      variant={variant}
      className={cn(
        "rounded-md border border-border/70 bg-transparent p-0.5 shadow-none dark:border-zinc-700 dark:bg-zinc-900",
        className
      )}
      itemClassName={cn(
        "h-7 min-w-24 rounded-[5px] px-4 text-xs",
        itemClassName
      )}
      activePillClassName={cn(
        "rounded-[5px] shadow-none ring-0",
        activePillClassName
      )}
    />
  );
}
