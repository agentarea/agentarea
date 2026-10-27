import { StatStripSkeleton } from "@/components/Overview/OverviewSkeleton";
import { Skeleton } from "@/components/ui/skeleton";

// Mirrors the metrics page: the period caption, then the four-up stat strip
// on the overview's ground.
export default function Loading() {
  return (
    <div aria-hidden="true" className="bg-muted/20 px-4 pb-11 pt-[18px]">
      <div className="mb-2 flex h-4 items-center gap-1.5 px-0.5">
        <Skeleton className="h-3.5 w-3.5 rounded-sm" />
        <Skeleton className="h-3 w-36" />
      </div>
      <StatStripSkeleton />
    </div>
  );
}
