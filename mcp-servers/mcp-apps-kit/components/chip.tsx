import type { ComponentProps } from "react";
import { cn } from "../lib/utils";

export type Tone = "neutral" | "danger" | "warning" | "success" | "info";

const TONES: Record<Tone, string> = {
  neutral: "text-muted-foreground",
  danger: "border-danger/40 text-danger bg-danger-surface",
  warning: "border-warning/40 text-warning bg-warning-surface",
  success: "border-success/40 text-success bg-success-surface",
  info: "border-info/40 text-info bg-info-surface",
};

/** The one small pill every app uses: a hairline border, 11px text, an optional 12px icon. */
export function Chip({ tone = "neutral", className, ...props }: ComponentProps<"span"> & { tone?: Tone }) {
  return (
    <span
      className={cn(
        "inline-flex h-5 max-w-full shrink-0 items-center gap-1 rounded-full border px-1.5 text-[11px] leading-none [&_svg]:size-3 [&_svg]:shrink-0",
        TONES[tone],
        className,
      )}
      {...props}
    />
  );
}

/** A label color name from the kit palette: red, orange, yellow, green, teal, blue, purple, pink, gray. */
export const labelColor = (color: string | undefined) => `var(--label-${color ?? "gray"})`;

/** A chip with a colored dot, for labels and categories. */
export function LabelChip({ name, color, className }: { name: string; color?: string; className?: string }) {
  return (
    <Chip className={className}>
      <span className="size-1.5 shrink-0 rounded-full" style={{ background: labelColor(color) }} aria-hidden />
      <span className="truncate">{name}</span>
    </Chip>
  );
}
