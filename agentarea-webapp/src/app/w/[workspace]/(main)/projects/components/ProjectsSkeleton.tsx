import { CollectionSkeleton, type SkeletonColumn } from "@/components/Skeleton";
import { Skeleton } from "@/components/ui/skeleton";
import { CARD_GRID_LOOSE } from "@/lib/collectionGrids";

// Mirrors the project card in ProjectsContent: icon + name, a 2-line
// description, then the agent / skill / MCP counts at the bottom.
function ProjectCardSkeleton() {
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
      <div className="mt-auto flex items-center gap-3 pt-1">
        <Skeleton className="h-3.5 w-8" />
        <Skeleton className="h-3.5 w-8" />
        <Skeleton className="h-3.5 w-8" />
      </div>
    </div>
  );
}

// The table columns of ProjectsContent.
const COLUMNS: SkeletonColumn[] = [
  { header: "Project", barClassName: "h-4 w-40" },
  { header: "Agents", barClassName: "h-3.5 w-6" },
  { header: "Skills", barClassName: "h-3.5 w-6" },
  { header: "MCP", barClassName: "h-3.5 w-6" },
  { header: "Instructions", barClassName: "h-3.5 w-8" },
];

export default function ProjectsSkeleton({ viewMode }: { viewMode?: string }) {
  return (
    <CollectionSkeleton
      viewMode={viewMode}
      columns={COLUMNS}
      gridClassName={CARD_GRID_LOOSE}
      count={8}
      Card={ProjectCardSkeleton}
    />
  );
}
