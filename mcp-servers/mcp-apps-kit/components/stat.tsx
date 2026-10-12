import type { ReactNode } from "react";
import { cn } from "../lib/utils";

/** Key figures as one bordered strip, cells split by hairlines; it wraps into rows on narrow screens. */
export function StatGroup({ label, className, children }: { label: string; className?: string; children: ReactNode }) {
  return (
    <section
      aria-label={label}
      className={cn("bg-border grid grid-cols-2 gap-px overflow-hidden rounded-lg border lg:grid-cols-4", className)}
    >
      {children}
    </section>
  );
}

export function Stat({
  label,
  value,
  note,
  badge,
  tone,
  icon,
}: {
  label: ReactNode;
  value: ReactNode;
  note?: ReactNode;
  badge?: ReactNode;
  tone?: "danger";
  icon?: ReactNode;
}) {
  return (
    <div className="bg-card flex min-w-0 flex-col gap-1 px-3 py-2.5">
      <div className="text-muted-foreground flex min-w-0 items-center gap-1.5 text-xs [&>svg]:size-3.5 [&>svg]:shrink-0">
        {icon}
        <span className="truncate">{label}</span>
      </div>
      <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
        <span
          className={cn(
            "tabular truncate text-lg leading-6 font-semibold tracking-tight",
            tone === "danger" && "text-danger",
          )}
        >
          {value}
        </span>
        {badge}
      </div>
      {note !== undefined && <p className="text-subtle-foreground tabular truncate text-[11px]">{note}</p>}
    </div>
  );
}
