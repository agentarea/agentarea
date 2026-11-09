import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** One section of a board: a column of content with optional crop marks. */
export function BoardCell({
  children,
  padded = true,
  className,
  markers,
}: {
  children: ReactNode;
  /** Adds the default cell padding. Turn off for full-bleed scrolling lists. */
  padded?: boolean;
  className?: string;
  /** Crop marks rendered at this cell's corners (desktop only). */
  markers?: ReactNode;
}) {
  return (
    <section
      className={cn(
        "relative flex min-h-0 min-w-0 flex-col",
        padded && "px-6 pb-4 pt-3.5",
        className
      )}
    >
      {children}
      {markers}
    </section>
  );
}
