import { SectionCard } from "@/components/Overview/OverviewCard";
import {
  CardHeadSkeleton,
  OverviewHeroSkeleton,
  RowSkeleton,
  StatStripSkeleton,
} from "@/components/Overview/OverviewSkeleton";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * Loading placeholder mirroring the trigger overview layout: full-bleed hero,
 * the four-up stat strip and the two-column body (task · runs / context).
 */
export default function TriggerOverviewSkeleton() {
  return (
    <div
      aria-hidden="true"
      className="md:flex md:h-full md:min-h-0 md:flex-col md:overflow-hidden"
    >
      <OverviewHeroSkeleton />

      <div className="w-full bg-muted/20 px-4 pb-11 pt-[18px] md:min-h-0 md:flex-1 md:overflow-y-auto md:overscroll-contain">
        <StatStripSkeleton />

        <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)]">
          <div className="flex flex-col gap-4">
            <SectionCard>
              <CardHeadSkeleton />
              <div className="space-y-2 px-[15px] py-3">
                <Skeleton className="h-3 w-full" />
                <Skeleton className="h-3 w-4/5" />
                <Skeleton className="h-3 w-2/3" />
              </div>
            </SectionCard>
            <SectionCard>
              <CardHeadSkeleton />
              {Array.from({ length: 3 }).map((_, i) => (
                <RowSkeleton
                  titleClassName="h-3 w-40"
                  subClassName="w-24"
                  key={i}
                />
              ))}
            </SectionCard>
          </div>

          <div className="flex flex-col gap-4">
            <SectionCard>
              <CardHeadSkeleton />
              {Array.from({ length: 4 }).map((_, i) => (
                <RowSkeleton
                  titleClassName="h-3 w-40"
                  subClassName="w-24"
                  key={i}
                  tile
                />
              ))}
            </SectionCard>
            <SectionCard>
              <CardHeadSkeleton />
              {Array.from({ length: 3 }).map((_, i) => (
                <RowSkeleton
                  titleClassName="h-3 w-40"
                  subClassName="w-24"
                  key={i}
                />
              ))}
            </SectionCard>
          </div>
        </div>
      </div>
    </div>
  );
}
