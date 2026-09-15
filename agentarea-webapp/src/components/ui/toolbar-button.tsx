import { forwardRef, type ComponentPropsWithoutRef } from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export interface ToolbarButtonProps extends ComponentPropsWithoutRef<"button"> {
  /** Leading glyph. */
  icon: LucideIcon;
  /** Toggle state — renders the raised "pressed" pill when true. */
  active?: boolean;
  iconClassName?: string;
  /** Class on the label span — pass a responsive `hidden …:inline` to collapse
   *  to icon-only when the toolbar is cramped. */
  labelClassName?: string;
}

/**
 * Compact toolbar button used across list/collection toolbars (Skills filters &
 * display menu, Triggers mobile filter, …). Matches the Skills toolbar styling:
 * an h-7 pill with a muted leading icon and an optional label, with an
 * active/pressed state. `forwardRef` + prop spread so it can be dropped into a
 * Radix `PopoverTrigger asChild` / `DropdownMenuTrigger asChild`.
 */
export const ToolbarButton = forwardRef<HTMLButtonElement, ToolbarButtonProps>(
  function ToolbarButton(
    {
      icon: Icon,
      active = false,
      className,
      iconClassName,
      labelClassName,
      children,
      type = "button",
      ...props
    },
    ref
  ) {
    return (
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
      >
        <Icon className={cn("h-3.5 w-3.5 text-muted-foreground", iconClassName)} />
        {children != null ? (
          <span className={labelClassName}>{children}</span>
        ) : null}
      </button>
    );
  }
);
