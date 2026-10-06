import type { ReactNode } from "react";
import { SectionCard } from "@/components/Overview/OverviewCard";

/** A titled group of settings: heading and optional lead above one panel of rows. */
export function SettingsSection({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <section className="space-y-2.5">
      <div className="space-y-0.5">
        <h3>{title}</h3>
        {description && (
          <p className="text-xs text-muted-foreground">{description}</p>
        )}
      </div>
      <SectionCard>{children}</SectionCard>
    </section>
  );
}

/**
 * The panel's bottom strip: a status line on the left, its actions on the right.
 * It always follows a row, whose bottom border is the divider.
 */
export function SettingsFooter({
  status,
  children,
}: {
  status?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center justify-end gap-2 bg-muted/20 px-4 py-2.5">
      {status != null && (
        <div className="mr-auto min-w-0 text-xs text-muted-foreground">
          {status}
        </div>
      )}
      {children}
    </div>
  );
}
