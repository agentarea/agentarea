import type { ReactNode } from "react";
import { cn } from "../lib/utils";

/** The side panel of a detail view: one labelled control per row. */
export function PropertyPanel({
  label = "Properties",
  className,
  children,
}: {
  label?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <aside className={cn("bg-card flex flex-col gap-3 rounded-lg border p-3", className)} aria-label={label}>
      {children}
    </aside>
  );
}

export function PropertyRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[72px_minmax(0,1fr)] items-start gap-2">
      <span className="text-muted-foreground pt-1.5 text-xs">{label}</span>
      <div className="flex min-w-0 flex-col gap-1">{children}</div>
    </div>
  );
}

/** A read-only value in a property row, aligned with the controls around it. */
export function PropertyValue({ className, children }: { className?: string; children: ReactNode }) {
  return <span className={cn("min-w-0 pt-1.5 text-[13px]", className)}>{children}</span>;
}

/** Who and when, under a rule at the foot of the panel. */
export function PropertyFooter({ children }: { children: ReactNode }) {
  return <div className="text-muted-foreground flex flex-col gap-1.5 border-t pt-3 text-xs">{children}</div>;
}

/** Main column and properties side by side on wide screens; properties first on narrow ones. */
export function DetailLayout({ main, aside }: { main: ReactNode; aside: ReactNode }) {
  return (
    <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_280px]">
      <div className="order-last flex min-w-0 flex-col gap-6 lg:order-none">{main}</div>
      {aside}
    </div>
  );
}
