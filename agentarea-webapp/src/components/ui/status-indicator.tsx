import * as React from "react";
import { Check } from "lucide-react";
import type { StatusIcon, StatusIndicatorSize, StatusTone } from "@/lib/status";
import { cn } from "@/lib/utils";

const TONE_STYLES = {
  success: {
    text: "text-emerald-600 dark:text-emerald-400",
    dot: "bg-emerald-500",
    halo: "bg-emerald-100/80 dark:bg-emerald-500/30",
    solid: "bg-emerald-500 text-white",
  },
  warning: {
    text: "text-amber-600 dark:text-amber-400",
    dot: "bg-amber-500",
    halo: "bg-amber-100/80 dark:bg-amber-500/30",
    solid: "bg-amber-500 text-white",
  },
  danger: {
    text: "text-red-600 dark:text-red-400",
    dot: "bg-red-500",
    halo: "bg-red-100/80 dark:bg-red-500/30",
    solid: "bg-red-500 text-white",
  },
  info: {
    text: "text-sky-600 dark:text-sky-400",
    dot: "bg-sky-500",
    halo: "bg-sky-100/80 dark:bg-sky-500/30",
    solid: "bg-sky-500 text-white",
  },
  neutral: {
    text: "text-muted-foreground",
    dot: "bg-zinc-400 dark:bg-zinc-500",
    halo: "bg-zinc-100/80 dark:bg-zinc-500/30",
    solid: "bg-zinc-400 text-white dark:bg-zinc-500",
  },
  brand: {
    text: "text-primary",
    dot: "bg-primary",
    halo: "bg-primary/15",
    solid: "bg-primary text-primary-foreground",
  },
} satisfies Record<
  StatusTone,
  { text: string; dot: string; halo: string; solid: string }
>;

const SIZE_STYLES = {
  default: {
    root: "gap-2 text-[12.5px]",
    dotWrap: "h-[12px] w-[12px]",
    halo: "h-[12px] w-[12px]",
    dot: "h-[6px] w-[6px]",
    glyph: "h-[8px] w-[8px]",
  },
  sm: {
    root: "gap-1.5 text-xs",
    dotWrap: "h-[10px] w-[10px]",
    halo: "h-[10px] w-[10px]",
    dot: "h-[5px] w-[5px]",
    glyph: "h-[7px] w-[7px]",
  },
} satisfies Record<
  StatusIndicatorSize,
  { root: string; dotWrap: string; halo: string; dot: string; glyph: string }
>;

export type StatusIndicatorTone = StatusTone;
export type { StatusIndicatorSize } from "@/lib/status";

export interface StatusIndicatorProps
  extends React.HTMLAttributes<HTMLSpanElement> {
  tone?: StatusIndicatorTone;
  size?: StatusIndicatorSize;
  dotClassName?: string;
  haloClassName?: string;
  pulse?: boolean;
  /** Replaces the dot with a filled marker. Terminal states only — a pulse
      would contradict it, so it wins over `pulse`. */
  icon?: StatusIcon;
}

export function StatusIndicator({
  tone = "neutral",
  size = "default",
  className,
  dotClassName,
  haloClassName,
  pulse = false,
  icon,
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
          "relative inline-flex shrink-0 items-center justify-center",
          sizeStyles.dotWrap
        )}
      >
        {icon === "check" ? (
          <span
            className={cn(
              "absolute inset-0 inline-flex items-center justify-center rounded-full",
              toneStyles.solid,
              dotClassName
            )}
          >
            <Check className={sizeStyles.glyph} strokeWidth={3.5} />
          </span>
        ) : (
          <>
            <span
              className={cn(
                "absolute inset-0 m-auto rounded-full",
                toneStyles.halo,
                sizeStyles.halo,
                haloClassName
              )}
            />
            {pulse && (
              <span
                className={cn(
                  "absolute inset-0 m-auto rounded-full animate-ping",
                  toneStyles.halo,
                  sizeStyles.halo,
                  haloClassName
                )}
              />
            )}
            <span
              className={cn(
                "relative rounded-full",
                toneStyles.dot,
                sizeStyles.dot,
                dotClassName
              )}
            />
          </>
        )}
      </span>
      {children ? <span>{children}</span> : null}
    </span>
  );
}
