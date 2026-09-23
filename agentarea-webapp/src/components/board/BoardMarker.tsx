import type { CSSProperties } from "react";
import { cn } from "@/lib/utils";

const crossBackground = (color: string) =>
  `linear-gradient(${color},${color}) center / 1.4px 11px no-repeat, ` +
  `linear-gradient(${color},${color}) center / 11px 1.4px no-repeat`;

type BoardMarkerProps = {
  className?: string;
  color?: string;
  visibleFrom?: "base" | "lg";
  style?: CSSProperties;
};

/** Technical registration cross used where dashed board lines meet an edge. */
export function BoardCrossMark({
  className,
  color = "var(--board-crop)",
  visibleFrom = "lg",
  style,
}: BoardMarkerProps) {
  return (
    <span
      aria-hidden
      className={cn(
        "pointer-events-none absolute z-[6] h-[11px] w-[11px]",
        visibleFrom === "lg" ? "hidden lg:block" : "block",
        className
      )}
      style={{ ...style, background: crossBackground(color) }}
    />
  );
}

/** Ring variant used at interior board-line intersections. */
export function BoardRingMark({
  className,
  color = "var(--board-crop)",
  visibleFrom = "lg",
  style,
}: BoardMarkerProps) {
  return (
    <span
      aria-hidden
      className={cn(
        "pointer-events-none absolute z-[6] h-[9px] w-[9px] rounded-full border-[1.5px] bg-background",
        visibleFrom === "lg" ? "hidden lg:block" : "block",
        className
      )}
      style={{ ...style, borderColor: color }}
    />
  );
}
