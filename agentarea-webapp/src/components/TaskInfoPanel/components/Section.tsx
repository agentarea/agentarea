import { ReactNode } from "react";
import { cn } from "@/lib/utils";

interface SectionProps {
  title: string;
  /** A control of the section's own at the right of its header. */
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  headerClassName?: string;
  contentClassName?: string;
}

export default function Section({
  title,
  action,
  children,
  className,
  headerClassName,
  contentClassName,
}: SectionProps) {
  return (
    <section
      className={cn(
        "rounded-md border border-border bg-card text-card-foreground shadow-sm overflow-hidden",
        className
      )}
    >
      <div
        className={cn(
          "flex min-h-6 items-center justify-between gap-2 border-b border-border bg-sidebar px-3 py-1",
          headerClassName
        )}
      >
        <h4 className="text-xs font-normal uppercase tracking-wide text-muted-foreground">
          {title}
        </h4>
        {action}
      </div>
      <div className={cn("p-3", contentClassName)}>{children}</div>
    </section>
  );
}
