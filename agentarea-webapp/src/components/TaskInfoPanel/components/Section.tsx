import { cn } from "@/lib/utils";
import { ReactNode } from "react";

interface SectionProps {
  title: string;
  children: ReactNode;
  className?: string;
  headerClassName?: string;
  contentClassName?: string;
}

export default function Section({
  title,
  children,
  className,
  headerClassName,
  contentClassName,
}: SectionProps) {
  return (
    <section
      className={cn(
        "rounded-md border border-border bg-card text-card-foreground shadow-sm",
        className
      )}
    >
      <div
        className={cn(
          "border-b border-border bg-muted/50 px-3 py-1",
          headerClassName
        )}
      >
        <h4 className="text-xs font-normal uppercase tracking-wide text-muted-foreground">
          {title}
        </h4>
      </div>
      <div className={cn("p-3", contentClassName)}>{children}</div>
    </section>
  );
}
