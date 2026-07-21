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
    <div className="-mx-4 -mt-5" aria-hidden="true">
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          className="flex items-center gap-3 border-b border-zinc-200 px-4 py-2.5 dark:border-zinc-700"
        >
          <Skeleton className="h-[22px] w-[22px] shrink-0 rounded-md" />
          <Skeleton className="h-4 w-40 shrink-0" />
          <Skeleton className="hidden h-3 flex-1 md:block" />
          <Skeleton className="h-[22px] w-20 shrink-0 rounded-full" />
          <div className="hidden items-center gap-1.5 md:flex">
            <Skeleton className="h-5 w-5 shrink-0 rounded-md" />
            <Skeleton className="h-3 w-20" />
          </div>
          <Skeleton className="hidden h-3 w-14 shrink-0 lg:block" />
          <Skeleton className="h-4 w-16 shrink-0 rounded-full" />
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
    <div className={CARD_GRID_DENSE} aria-hidden="true">
      {Array.from({ length: 10 }).map((_, i) => (
        <TriggerCardSkeleton key={i} />
      ))}
    </div>
  );
}
