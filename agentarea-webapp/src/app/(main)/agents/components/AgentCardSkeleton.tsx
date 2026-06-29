import { Skeleton } from "@/components/ui/skeleton";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/**
 * Loading placeholder for `AgentCard`. Mirrors its exact structure — avatar +
 * title row, model badge, and the bordered footer with tool chips — so the grid
 * doesn't shift when real data replaces the skeleton.
 */
export default function AgentCardSkeleton() {
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
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 flex-1 pt-0.5">
              <div className="flex items-center gap-2">
                {/* avatar — AgentAvatar size="sm" is h-6 w-6 rounded-md */}
                <Skeleton className="h-6 w-6 shrink-0 rounded-md" />
                <Skeleton className="h-4 w-32" />
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                {/* model badge */}
                <Skeleton className="h-5 w-24 rounded-full" />
              </div>
            </div>
          </div>
        </div>

        <div
          className={cn(
            "relative overflow-hidden border-t",
            "border-zinc-200/60 dark:border-zinc-700/60",
            "pl-[16px] pr-[8px] py-[10px] md:pl-[20px] md:pr-[10px] lg:pl-[24px] lg:pr-[10px]"
          )}
        >
          <div className="relative z-10 flex items-center justify-between">
            {/* tool chips — overlapping h-6 w-6 circles */}
            <div className="flex -space-x-1.5">
              <Skeleton className="h-6 w-6 rounded-full" />
              <Skeleton className="h-6 w-6 rounded-full" />
              <Skeleton className="h-6 w-6 rounded-full" />
            </div>
            <Skeleton className="h-4 w-4 rounded-sm" />
          </div>
        </div>
      </div>
    </Card>
  );
}
