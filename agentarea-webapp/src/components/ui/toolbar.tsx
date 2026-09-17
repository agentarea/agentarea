import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Compact, Linear-style toolbar button used in page subheaders (Skills
 * filters/display, Dashboard period, Members display). Put a 14px icon and a
 * label inside; `active` shows the pressed/open state.
 */
export const ToolbarButton = React.forwardRef<
  HTMLButtonElement,
  React.ButtonHTMLAttributes<HTMLButtonElement> & { active?: boolean }
>(({ className, active = false, type = "button", ...props }, ref) => (
  <button
    ref={ref}
    type={type}
    className={cn(
      "inline-flex h-7 shrink-0 items-center gap-1.5 rounded-md px-2 text-[12.5px] font-normal transition-colors",
      active
        ? "bg-muted text-foreground"
        : "text-foreground/80 hover:bg-muted/60",
      className
    )}
    {...props}
  />
));
ToolbarButton.displayName = "ToolbarButton";

/** Thin vertical divider between toolbar groups. */
export function ToolbarDivider({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "mx-1 h-[18px] w-px shrink-0 bg-zinc-200 dark:bg-zinc-700",
        className
      )}
    />
  );
}
