import type { ReactNode } from "react";
import { EntityAvatar } from "@/components/ui/entity-avatar";
import { cn } from "@/lib/utils";

/**
 * Section header used inside a board cell: a soft-tinted role tile with an
 * icon, the section title, an optional count pill, and right-aligned meta.
 */
export function BoardSectionHeader({
  icon,
  color,
  title,
  meta,
  pill,
  className,
}: {
  icon: ReactNode;
  /** Role color for the soft tile (any CSS color, incl. `hsl(var(--x))`). */
  color: string;
  title: string;
  meta?: ReactNode;
  pill?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <EntityAvatar variant="soft" size={22} color={color} icon={icon} lines={false} />
      <h2 className="m-0 text-[15px] font-semibold tracking-[-0.018em] text-foreground">
        {title}
      </h2>
      {pill != null && (
        <span className="rounded-full bg-muted px-2 py-px text-[11.5px] font-medium text-muted-foreground">
          {pill}
        </span>
      )}
      <span className="flex-1" />
      {meta != null && (
        <span className="text-[12px] font-medium text-muted-foreground">{meta}</span>
      )}
    </div>
  );
}
