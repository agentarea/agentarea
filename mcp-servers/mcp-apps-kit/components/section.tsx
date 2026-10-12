import type { ReactNode } from "react";
import { cn } from "../lib/utils";

/** A titled block of a view: "Sub-issues 3/3 done", "Activity", "Accounts". */
export function Section({
  title,
  meta,
  actions,
  className,
  children,
  label,
}: {
  title: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
  className?: string;
  children: ReactNode;
  label?: string;
}) {
  return (
    <section
      className={cn("flex min-w-0 flex-col gap-2", className)}
      aria-label={label ?? (typeof title === "string" ? title : undefined)}
    >
      <div className="flex items-center gap-2">
        <h2 className="flex min-w-0 items-center gap-2 text-sm font-semibold">
          {title}
          {meta !== undefined && (
            <span className="text-muted-foreground tabular truncate text-xs font-normal">{meta}</span>
          )}
        </h2>
        {actions && <div className="ml-auto flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
      {children}
    </section>
  );
}
