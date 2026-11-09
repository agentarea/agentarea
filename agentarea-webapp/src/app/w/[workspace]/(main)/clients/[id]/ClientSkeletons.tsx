import { SectionCard } from "@/components/Overview/OverviewCard";
import {
  CardHeadSkeleton,
  OverviewHeroSkeleton,
  RowSkeleton,
  StatStripSkeleton,
} from "@/components/Overview/OverviewSkeleton";

/** The two-column body of a harness tab: a wide column and a rail of cards. */
function CardColumnsSkeleton({ rows }: { rows: [number, number] }) {
  return (
    <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)]">
      {rows.map((count, column) => (
        <SectionCard key={column}>
          <CardHeadSkeleton />
          {Array.from({ length: count }).map((_, i) => (
            <RowSkeleton
              key={i}
              tile
              titleClassName="h-3 w-32"
              subClassName="w-20"
            />
          ))}
        </SectionCard>
      ))}
    </div>
  );
}

/** Loading placeholder mirroring the harness overview: hero, stats, cards. */
export function ClientOverviewSkeleton() {
  return (
    <div
      aria-hidden="true"
      className="md:flex md:h-full md:min-h-0 md:flex-col md:overflow-hidden"
    >
      <OverviewHeroSkeleton />
      <div className="w-full px-4 pb-11 pt-[18px] md:min-h-0 md:flex-1 md:overflow-y-auto">
        <StatStripSkeleton />
        <CardColumnsSkeleton rows={[2, 3]} />
      </div>
    </div>
  );
}

/** Loading placeholder for the Tools and Runner tabs. */
export function ClientTabSkeleton() {
  return (
    <div aria-hidden="true" className="w-full px-4 pb-11 pt-[18px]">
      <CardColumnsSkeleton rows={[5, 3]} />
    </div>
  );
}
