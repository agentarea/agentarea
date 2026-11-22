import { SectionCard } from "@/components/Overview/OverviewCard";
import {
  CardHeadSkeleton,
  OverviewHeroSkeleton,
  RowSkeleton,
  StatStripSkeleton,
} from "@/components/Overview/OverviewSkeleton";

/**
 * Loading placeholder mirroring the member overview: hero, stat strip, recent
 * tasks on the left, access and automations on the right.
 */
export default function MemberOverviewSkeleton() {
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
              {Array.from({ length: 5 }).map((_, i) => (
                <RowSkeleton
                  titleClassName="h-3 w-56"
                  subClassName="w-24"
                  key={i}
                />
              ))}
            </SectionCard>
          </div>

          <div className="flex flex-col gap-4">
            <SectionCard>
              <CardHeadSkeleton />
              {Array.from({ length: 2 }).map((_, i) => (
                <RowSkeleton
                  titleClassName="h-3 w-32"
                  subClassName="w-40"
                  key={i}
                  tile
                />
              ))}
            </SectionCard>
            <SectionCard>
              <CardHeadSkeleton />
              {Array.from({ length: 2 }).map((_, i) => (
                <RowSkeleton
                  titleClassName="h-3 w-40"
                  subClassName="w-24"
                  key={i}
                  tile
                />
              ))}
            </SectionCard>
          </div>
        </div>
      </div>
    </div>
  );
}
