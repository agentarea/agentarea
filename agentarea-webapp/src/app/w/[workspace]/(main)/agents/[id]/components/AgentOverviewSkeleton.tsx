import { SectionCard, StatStrip } from "@/components/Overview/OverviewCard";
import {
  CardHeadSkeleton,
  OverviewHeroSkeleton,
  RowSkeleton,
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

      <div className="w-full px-4 pb-11 pt-[18px] md:min-h-0 md:flex-1 md:overflow-y-auto md:overscroll-contain">
        <StatStrip>
          {Array.from({ length: 4 }).map((_, i) => (
            <div
              key={i}
              className="min-w-0 space-y-2.5 border-dashed px-4 py-[13px] [border-color:var(--board-line)] even:border-l [&:nth-child(n+3)]:border-t lg:border-l lg:first:border-l-0 lg:[&:nth-child(n+3)]:border-t-0"
            >
              <Skeleton className="h-3 w-20" />
              <Skeleton className="h-6 w-24" />
              <Skeleton className="h-[5px] w-full rounded-[2px]" />
              <Skeleton className="h-2.5 w-28" />
            </div>
          ))}
        </StatStrip>

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
