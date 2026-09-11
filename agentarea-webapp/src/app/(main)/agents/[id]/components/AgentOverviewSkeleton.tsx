import { Skeleton } from "@/components/ui/skeleton";
import { SectionCard, StatStrip } from "./OverviewCard";

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
      <div className="border-b border-border md:shrink-0">
        <div className="flex w-full items-start gap-3 px-4 pb-[14px] pt-[13px]">
          <Skeleton className="mt-0.5 h-[34px] w-[34px] rounded-[5px]" />
          <div className="min-w-0 flex-1 space-y-2">
            <div className="flex items-center gap-2.5">
              <Skeleton className="h-5 w-52" />
              <Skeleton className="h-3.5 w-14" />
            </div>
            <Skeleton className="h-3.5 w-full max-w-[560px]" />
            <div className="flex gap-3.5">
              <Skeleton className="h-3 w-32" />
              <Skeleton className="h-3 w-20" />
              <Skeleton className="h-3 w-24" />
            </div>
          </div>
        </div>
      </div>

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

function CardHeadSkeleton() {
  return (
    <div className="flex items-center gap-[9px] border-b border-border/60 px-[15px] py-[11px]">
      <Skeleton className="h-[23px] w-[23px] rounded" />
      <Skeleton className="h-3.5 w-24" />
      <span className="flex-1" />
      <Skeleton className="h-3 w-16" />
    </div>
  );
}

function RowSkeleton({ tile = false }: { tile?: boolean }) {
  return (
    <div className="flex items-center gap-[11px] border-b border-border/60 px-[15px] py-[11px] last:border-b-0">
      {tile && <Skeleton className="h-7 w-7 rounded" />}
      <div className="min-w-0 flex-1 space-y-1.5">
        <Skeleton className="h-3.5 w-3/5" />
        <Skeleton className="h-2.5 w-2/5" />
      </div>
      <Skeleton className="h-3 w-12" />
    </div>
  );
}
