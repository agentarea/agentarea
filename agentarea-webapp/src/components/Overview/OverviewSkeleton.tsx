import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/**
 * Loading pieces for the detail-page overviews (agent, trigger, project): the
 * `OverviewHero` band, a `SectionCardHead`, and one row of a section card.
 */

export function OverviewHeroSkeleton({
  meta = true,
}: {
  /** Whether the hero has a meta row under its description. */
  meta?: boolean;
} = {}) {
  return (
    <div className="border-b border-border md:shrink-0">
      <div className="flex w-full items-start gap-3 px-4 pb-[14px] pt-[13px]">
        <Skeleton className="mt-0.5 h-[34px] w-[34px] rounded-[5px]" />
        <div className="min-w-0 flex-1 space-y-2">
          <div className="flex items-center gap-2.5">
            <Skeleton className="h-5 w-52" />
            <Skeleton className="h-3.5 w-14" />
          </div>
          <Skeleton className="h-3.5 w-full max-w-[560px]" />
          {meta && (
            <div className="flex gap-3.5">
              <Skeleton className="h-3 w-32" />
              <Skeleton className="h-3 w-20" />
              <Skeleton className="h-3 w-24" />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export function CardHeadSkeleton() {
  return (
    <div className="flex items-center gap-[9px] border-b border-border/60 px-[15px] py-[11px]">
      <Skeleton className="h-[23px] w-[23px] rounded" />
      <Skeleton className="h-3.5 w-24" />
      <span className="flex-1" />
      <Skeleton className="h-3 w-16" />
    </div>
  );
}

export function RowSkeleton({
  tile = false,
  titleClassName = "w-3/5",
  subClassName = "w-2/5",
}: {
  tile?: boolean;
  /** Width of the title bar. */
  titleClassName?: string;
  /** Width of the sub-line bar. */
  subClassName?: string;
}) {
  return (
    <div className="flex items-center gap-[11px] border-b border-border/60 px-[15px] py-[11px] last:border-b-0">
      {tile && <Skeleton className="h-7 w-7 rounded" />}
      <div className="min-w-0 flex-1 space-y-1.5">
        <Skeleton className={cn("h-3.5", titleClassName)} />
        <Skeleton className={cn("h-2.5", subClassName)} />
      </div>
      <Skeleton className="h-3 w-12" />
    </div>
  );
}
