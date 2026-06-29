import { Skeleton } from "@/components/ui/skeleton";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface LinkedCardSkeletonProps {
  /** Show the leading 40px icon box (TriggerCard, MCPCard, ProviderConfigCard). */
  icon?: boolean;
  /** Show a subtitle row of small chips under the title (badge + status). */
  subtitle?: boolean;
  /** Show a top-right badge placeholder (TaskItem status). */
  topRight?: boolean;
  /** Number of body content lines rendered in the `mt-auto` area. */
  lines?: number;
  className?: string;
}

/**
 * Loading placeholder for `LinkedCard`. Mirrors its padding, icon box, title /
 * subtitle layout, body area, and the trailing hover-link arrow, so any grid of
 * LinkedCards (tasks, triggers, connections, provider configs) keeps its shape
 * while loading. Toggle the parts each card uses via props.
 */
export default function LinkedCardSkeleton({
  icon = false,
  subtitle = false,
  topRight = false,
  lines = 0,
  className,
}: LinkedCardSkeletonProps) {
  return (
    <Card
      className={cn(
        "relative flex h-full cursor-default flex-col justify-between px-4 py-4",
        "border border-zinc-200 dark:border-zinc-800",
        "bg-white dark:bg-zinc-900",
        className
      )}
      aria-hidden="true"
    >
      <div className="z-10 flex h-full flex-col">
        <div className={cn("mb-2 flex gap-3", subtitle ? "items-start" : "items-center")}>
          {icon && (
            <Skeleton className="h-10 w-10 flex-shrink-0 rounded-lg" />
          )}

          <div className="min-w-0 flex-1">
            <div className={cn("flex justify-between gap-3", subtitle ? "items-start" : "items-center")}>
              <div className={cn("min-w-0 flex-1", subtitle && "pt-0.5")}>
                <Skeleton className={cn("h-4 w-3/4", subtitle && "mb-2")} />
                {subtitle && (
                  <div className="flex flex-wrap items-center gap-2">
                    <Skeleton className="h-4 w-16 rounded-full" />
                    <Skeleton className="h-4 w-12 rounded-full" />
                  </div>
                )}
              </div>
              {topRight && <Skeleton className="h-4 w-16 flex-shrink-0 rounded-full" />}
            </div>
          </div>
        </div>

        {lines > 0 && (
          <div className="mt-auto flex flex-col gap-2 py-2">
            {Array.from({ length: lines }).map((_, i) => (
              <Skeleton key={i} className="h-3 w-2/5" />
            ))}
          </div>
        )}
      </div>

      <div className="-mb-2 -mr-2 -mt-4 flex justify-end">
        <Skeleton className="h-4 w-4 rounded-sm" />
      </div>
    </Card>
  );
}
