import { CardGridSkeleton } from "@/components/Skeleton";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

const GRID_CLASS =
  "grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 p-4";

// Mirrors ProjectCard: title + 2-line description, bordered footer with 3 stat
// chips and the hover-link arrow.
function ProjectCardSkeleton() {
  return (
    <Card
      className={cn(
        "relative flex h-full flex-col justify-between overflow-hidden p-0",
        "border border-zinc-200 dark:border-zinc-800",
        "bg-white dark:bg-zinc-900"
      )}
      aria-hidden="true"
    >
      <div className="relative z-10 flex h-full flex-col justify-between">
        <div className="flex flex-col gap-2 px-[16px] py-[16px] md:px-[20px] lg:px-[24px]">
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-2/3" />
        </div>
        <div className="border-t border-zinc-200/60 py-[10px] pl-[16px] pr-[8px] md:pl-[20px] md:pr-[10px] lg:pl-[24px] lg:pr-[10px] dark:border-zinc-700/60">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Skeleton className="h-3.5 w-8" />
              <Skeleton className="h-3.5 w-8" />
              <Skeleton className="h-3.5 w-8" />
            </div>
            <Skeleton className="h-4 w-4 rounded-sm" />
          </div>
        </div>
      </div>
    </Card>
  );
}

export default function ProjectsSkeleton() {
  return (
    <CardGridSkeleton count={8} className={GRID_CLASS} Card={ProjectCardSkeleton} />
  );
}
