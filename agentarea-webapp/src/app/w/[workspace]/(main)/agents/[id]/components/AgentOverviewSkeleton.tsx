import { SectionCard } from "@/components/Overview/OverviewCard";
import {
  CardHeadSkeleton,
  OverviewHeroSkeleton,
  RowSkeleton,
  StatStripSkeleton,
} from "@/components/Overview/OverviewSkeleton";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * Loading placeholder mirroring the agent overview layout: full-bleed hero,
 * the four-up stat strip and the two-column body (tasks · glance/guardrails).
 */
export default function AgentOverviewSkeleton() {
  return (
    <div
      aria-hidden="true"
      className="md:flex md:h-full md:min-h-0 md:flex-col md:overflow-hidden"
    >
      <OverviewHeroSkeleton />

      <div className="w-full bg-muted/20 px-4 pb-11 pt-[18px] md:min-h-0 md:flex-1 md:overflow-y-auto md:overscroll-contain">
        <StatStripSkeleton />

        <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)]">
          <SectionCard>
            <CardHeadSkeleton />
            <Skeleton className="h-[30px] w-full rounded-none" />
            {Array.from({ length: 2 }).map((_, i) => (
              <RowSkeleton key={`r-${i}`} />
            ))}
            <Skeleton className="h-[30px] w-full rounded-none" />
            {Array.from({ length: 4 }).map((_, i) => (
              <RowSkeleton key={`c-${i}`} />
            ))}
          </SectionCard>

          <div className="flex flex-col gap-4">
            <SectionCard>
              <CardHeadSkeleton />
              {Array.from({ length: 3 }).map((_, i) => (
                <RowSkeleton key={i} tile />
              ))}
            </SectionCard>
            <SectionCard>
              <CardHeadSkeleton />
              <div className="space-y-2 border-b border-border/60 px-[15px] py-3">
                <div className="flex justify-between">
                  <Skeleton className="h-3 w-28" />
                  <Skeleton className="h-3 w-20" />
                </div>
                <Skeleton className="h-1.5 w-full rounded-[2px]" />
              </div>
              <RowSkeleton tile />
              <RowSkeleton tile />
            </SectionCard>
          </div>
        </div>
      </div>
    </div>
  );
}
