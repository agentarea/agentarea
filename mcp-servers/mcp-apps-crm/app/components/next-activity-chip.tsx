import { Chip } from "@kit/components/chip";
import type { DealRow } from "@shared/schema";
import { TriangleAlert } from "lucide-react";
import { relativeDay } from "@/lib/format";
import { ACTIVITY_META } from "@/lib/meta";

/** The deal's next step: red when overdue, a warning when nothing is planned. */
export function NextActivityChip({ deal, now, className }: { deal: DealRow; now: string; className?: string }) {
  const next = deal.nextActivity;
  if (!next) {
    return (
      <Chip tone="warning" className={className} title="Nothing is planned for this deal">
        <TriangleAlert />
        No next step
      </Chip>
    );
  }
  const Icon = ACTIVITY_META[next.type].icon;
  return (
    <Chip
      tone={next.overdue ? "danger" : "neutral"}
      className={className}
      title={`${ACTIVITY_META[next.type].label}: ${next.subject}`}
    >
      <Icon />
      <span className="truncate">
        {next.overdue ? `Overdue ${relativeDay(next.dueAt, now).toLowerCase()}` : relativeDay(next.dueAt, now)}
      </span>
    </Chip>
  );
}
