import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

interface DetailSkeletonProps {
  /** Number of info blocks in the two-column grid. */
  blocks?: number;
  className?: string;
}

/**
 * Generic loading placeholder for detail/overview pages: an identity header
 * (icon + title + subtitle) followed by a two-column grid of info blocks. Used
 * as the content skeleton under a detail page's persistent header/tabs chrome.
 */
export default function DetailSkeleton({
  blocks = 4,
  className,
}: DetailSkeletonProps) {
  return (
    <div className={cn("space-y-6", className)} aria-hidden="true">
      <div className="flex items-center gap-3">
        <Skeleton className="h-10 w-10 rounded-lg" />
        <div className="space-y-2">
          <Skeleton className="h-5 w-48" />
          <Skeleton className="h-3 w-32" />
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {Array.from({ length: blocks }).map((_, i) => (
          <div key={i} className="space-y-2 rounded-lg border border-border p-4">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-2/3" />
          </div>
        ))}
      </div>
    </div>
  );
}
