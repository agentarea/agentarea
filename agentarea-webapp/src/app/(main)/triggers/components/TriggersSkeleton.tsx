import { LinkedCardSkeleton } from "@/components/Skeleton";
import { Skeleton } from "@/components/ui/skeleton";
import { CARD_GRID_DENSE } from "@/lib/collectionGrids";

// TriggerCard: icon + (type badge / status) subtitle + optional agent row.
function TriggerCardSkeleton() {
  return <LinkedCardSkeleton icon subtitle lines={1} />;
}

// Mirrors a TriggersTable row: tile · name · schedule · type · agent · next · status.
function TriggersTableSkeleton({ rows = 8 }: { rows?: number }) {
  return (
    <div aria-hidden="true">
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          className="flex items-center gap-3 border-b border-zinc-200 px-4 py-2.5 dark:border-zinc-700"
        >
          <Skeleton className="h-[22px] w-[22px] shrink-0 rounded-md" />
          <Skeleton className="h-4 w-40 shrink-0" />
          <div className="min-w-0 flex-1" />
          {/* type */}
          <Skeleton className="h-[22px] w-16 shrink-0 rounded-full" />
          {/* agent */}
          <div className="hidden w-[160px] shrink-0 items-center gap-1.5 md:flex">
            <Skeleton className="h-5 w-5 shrink-0 rounded-md" />
            <Skeleton className="h-3 w-24" />
          </div>
          {/* next run */}
          <Skeleton className="hidden h-3 w-12 shrink-0 lg:block" />
          {/* status */}
          <Skeleton className="hidden h-4 w-[116px] shrink-0 rounded-full sm:block" />
        </div>
      ))}
    </div>
  );
}

interface TriggersSkeletonProps {
  viewMode?: "grid" | "table";
}

export default function TriggersSkeleton({ viewMode = "table" }: TriggersSkeletonProps) {
  if (viewMode === "table") return <TriggersTableSkeleton />;
  return (
    <div className={`p-4 ${CARD_GRID_DENSE}`} aria-hidden="true">
      {Array.from({ length: 10 }).map((_, i) => (
        <TriggerCardSkeleton key={i} />
      ))}
    </div>
  );
}
