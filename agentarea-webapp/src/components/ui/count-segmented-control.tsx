"use client";

import { motion } from "framer-motion";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export interface CountSegmentedControlItem<T extends string = string> {
  value: T;
  label: ReactNode;
  count?: ReactNode;
}

// Active-pill palette by role. Pick via the `variant` prop; the per-instance
// className props below still win (twMerge) for one-off tweaks.
export type CountSegmentedControlVariant = "subtle" | "solid";

const VARIANTS: Record<
  CountSegmentedControlVariant,
  { pill: string; activeText: string; activeCount: string }
> = {
  // Quiet secondary filter (e.g. inbox status filter): light raised pill.
  subtle: {
    pill: "bg-zinc-100 dark:bg-zinc-900",
    activeText: "text-foreground",
    activeCount: "text-muted-foreground dark:text-zinc-300",
  },
  // Primary page-level navigation (e.g. explore type switcher): solid pill
  // with inverted text. Theme-aware via foreground/background tokens, so it
  // flips to a light pill + dark text in dark mode.
  solid: {
    pill: "bg-foreground dark:bg-foreground",
    activeText: "text-background",
    activeCount: "text-background/70",
  },
};

interface CountSegmentedControlProps<T extends string = string> {
  items: CountSegmentedControlItem<T>[];
  value: T;
  onChange: (value: T) => void;
  variant?: CountSegmentedControlVariant;
  className?: string;
  itemClassName?: string;
  activePillClassName?: string;
  activeItemClassName?: string;
  inactiveItemClassName?: string;
  countClassName?: string;
  activeCountClassName?: string;
  layoutId?: string;
}

export function CountSegmentedControl<T extends string = string>({
  items,
  value,
  onChange,
  variant = "subtle",
  className,
  itemClassName,
  activePillClassName,
  activeItemClassName,
  inactiveItemClassName,
  countClassName,
  activeCountClassName,
  layoutId = "count-segmented-control",
}: CountSegmentedControlProps<T>) {
  const styles = VARIANTS[variant];
  return (
    <div
      className={cn(
        "inline-flex min-w-0 items-center gap-0.5 overflow-x-auto rounded-xl bg-transparent p-[3px] no-scrollbar",
        className
      )}
    >
      {items.map((item) => {
        const isActive = item.value === value;

        return (
          <button
            key={item.value}
            type="button"
            onClick={() => onChange(item.value)}
            className={cn(
              "relative inline-flex h-7 shrink-0 items-center gap-2 rounded-[10px] px-3 text-[12.5px] font-normal tracking-normal transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
              isActive
                ? styles.activeText
                : "text-muted-foreground hover:text-foreground dark:text-zinc-400 dark:hover:text-zinc-100",
              itemClassName,
              isActive ? activeItemClassName : inactiveItemClassName
            )}
          >
            {isActive ? (
              <motion.span
                layoutId={`${layoutId}-active-pill`}
                className={cn(
                  "absolute inset-0 rounded-[8px] ring-0 shadow-none",
                  styles.pill,
                  activePillClassName
                )}
                initial={false}
                transition={{
                  type: "spring",
                  stiffness: 380,
                  damping: 32,
                }}
              />
            ) : null}

            <span className="relative z-10">{item.label}</span>
            {item.count != null ? (
              <span
                className={cn(
                  "relative z-10 text-[11px] font-normal text-muted-foreground/80 transition-colors dark:text-zinc-500",
                  countClassName,
                  isActive && styles.activeCount,
                  isActive && activeCountClassName
                )}
              >
                {item.count}
              </span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
