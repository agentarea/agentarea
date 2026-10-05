import { SectionCard } from "@/components/Overview/OverviewCard";
import {
  CardHeadSkeleton,
  OverviewHeroSkeleton,
  RowSkeleton,
} from "@/components/Overview/OverviewSkeleton";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * Loading placeholder mirroring the project overview: the hero band, then
 * instructions + agents on the left and skills, connections and files on the
 * right.
 */
export default function ProjectOverviewSkeleton() {
  return (
    <div
      aria-hidden="true"
      className="md:flex md:h-full md:min-h-0 md:flex-col md:overflow-hidden"
    >
      <OverviewHeroSkeleton meta={false} />

      <div className="w-full bg-muted/20 px-4 pb-11 pt-[18px] md:min-h-0 md:flex-1 md:overflow-y-auto md:overscroll-contain">
        <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)]">
          <div className="flex min-w-0 flex-col gap-4">
            <SectionCard>
              <CardHeadSkeleton />
              <div className="space-y-2 px-[15px] py-3">
                <Skeleton className="h-3 w-full" />
                <Skeleton className="h-3 w-11/12" />
                <Skeleton className="h-3 w-3/4" />
              </div>
            </SectionCard>
            <SectionCard>
              <CardHeadSkeleton />
              {Array.from({ length: 4 }).map((_, i) => (
                <RowSkeleton key={i} tile />
              ))}
            </SectionCard>
          </div>

          <div className="flex min-w-0 flex-col gap-4">
            {Array.from({ length: 3 }).map((_, card) => (
              <SectionCard key={card}>
                <CardHeadSkeleton />
                {Array.from({ length: 2 }).map((_, i) => (
                  <RowSkeleton key={i} tile />
                ))}
              </SectionCard>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
