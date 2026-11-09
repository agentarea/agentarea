import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * One option of a pick-one grid: a bordered tile with an optional mark, a
 * title and a two-line description; the picked tile carries the primary
 * border. Shared by the agent preset picker and the trigger type picker.
 */
export function ChoiceTile({
  title,
  description,
  icon,
  selected = false,
  disabled = false,
  onClick,
  className,
}: {
  title: ReactNode;
  description?: ReactNode;
  icon?: ReactNode;
  selected?: boolean;
  /** Shown but fixed, e.g. a choice an edit cannot change. */
  disabled?: boolean;
  onClick: () => void;
  className?: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "flex min-w-0 items-start gap-2.5 rounded-md border px-3 py-2 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        selected
          ? "border-primary bg-primary/5"
          : "hover:bg-muted/50 dark:border-zinc-700",
        disabled && "cursor-default",
        className
      )}
    >
      {icon && <span className="mt-0.5 shrink-0">{icon}</span>}
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium">{title}</span>
        {description && (
          <span className="line-clamp-2 text-xs text-muted-foreground">
            {description}
          </span>
        )}
      </span>
    </button>
  );
}
