import { CollectionSkeleton, type SkeletonColumn } from "@/components/Skeleton";
import { Skeleton } from "@/components/ui/skeleton";
import { CARD_GRID_LOOSE } from "@/lib/collectionGrids";

// Mirrors the stream card in StreamsContent: icon + name, a 2-line
// description, then how long its events are kept.
function StreamCardSkeleton() {
  return (
    <div
      className="card card-shadow flex h-full cursor-default flex-col gap-3 hover:shadow-none"
      aria-hidden="true"
    >
      <div className="flex items-center gap-2">
        <Skeleton className="h-5 w-5 shrink-0 rounded-sm" />
        <Skeleton className="h-4 w-2/3" />
      </div>
      <div className="space-y-1.5">
        <Skeleton className="h-3.5 w-full" />
        <Skeleton className="h-3.5 w-3/4" />
      </div>
      <div className="mt-auto pt-1">
        <Skeleton className="h-3.5 w-16" />
      </div>
    </div>
  );
}

const COLUMNS: SkeletonColumn[] = [
  { header: "Stream", barClassName: "h-4 w-40" },
  { header: "Kept for", barClassName: "h-3.5 w-12" },
  { header: "Created", barClassName: "h-3.5 w-20" },
];

export default function StreamsSkeleton({ viewMode }: { viewMode?: string }) {
  return (
    <CollectionSkeleton
      viewMode={viewMode}
      columns={COLUMNS}
      gridClassName={CARD_GRID_LOOSE}
      count={8}
      Card={StreamCardSkeleton}
    />
  );
}
