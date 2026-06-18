import * as React from "react";
import { cn } from "@/lib/utils";

const TONE_STYLES = {
  success: {
    text: "text-emerald-600 dark:text-emerald-400",
    dot: "bg-emerald-500 ring-emerald-500/20",
  },
  warning: {
    text: "text-amber-600 dark:text-amber-400",
    dot: "bg-amber-500 ring-amber-500/20",
  },
  danger: {
    text: "text-red-600 dark:text-red-400",
    dot: "bg-red-500 ring-red-500/20",
  },
  info: {
    text: "text-sky-600 dark:text-sky-400",
    dot: "bg-sky-500 ring-sky-500/20",
  },
  neutral: {
    text: "text-muted-foreground",
    dot: "bg-zinc-400 ring-zinc-400/20 dark:bg-zinc-500 dark:ring-zinc-500/20",
  },
} as const;

const SIZE_STYLES = {
  default: {
    root: "gap-2 text-[12.5px]",
    dot: "h-[6px] w-[6px] ring-[3px]",
  },
  sm: {
    root: "gap-1.5 text-xs",
    dot: "h-[5px] w-[5px] ring-2",
  },
} as const;

export type StatusIndicatorTone = keyof typeof TONE_STYLES;
export type StatusIndicatorSize = keyof typeof SIZE_STYLES;

export interface StatusIndicatorProps
  extends React.HTMLAttributes<HTMLSpanElement> {
  tone?: StatusIndicatorTone;
  size?: StatusIndicatorSize;
  dotClassName?: string;
}

export function StatusIndicator({
  tone = "neutral",
  size = "default",
  className,
  dotClassName,
  children,
  ...props
}: StatusIndicatorProps) {
  const toneStyles = TONE_STYLES[tone];
  const sizeStyles = SIZE_STYLES[size];

  return (
    <span
      className={cn(
        "inline-flex w-fit items-center font-normal",
        toneStyles.text,
        sizeStyles.root,
        className
      )}
      {...props}
    >
      <span
        aria-hidden="true"
        className={cn(
          "rounded-full",
          toneStyles.dot,
          sizeStyles.dot,
          dotClassName
        )}
      />
      <span>{children}</span>
    </span>
  );
}
