import { cn } from "../lib/utils";
import { Skeleton } from "../ui/skeleton";

export function BoardSkeleton({ label = "Loading board" }: { label?: string }) {
  return (
    <div className="flex gap-3 overflow-hidden" aria-busy="true" aria-label={label}>
      {Array.from({ length: 4 }, (_, i) => (
        <div key={i} className="bg-muted/70 flex w-[272px] shrink-0 flex-col gap-1.5 rounded-lg p-1.5">
          <Skeleton className="m-1.5 h-4 w-24" />
          {Array.from({ length: 4 - (i % 2) }, (_, j) => (
            <Skeleton key={j} className="h-[76px] rounded-md" />
          ))}
        </div>
      ))}
    </div>
  );
}

export function DetailSkeleton({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex flex-col gap-4" aria-busy="true" aria-label={label}>
      <Skeleton className="h-4 w-48" />
      <Skeleton className="h-7 w-3/4" />
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_280px]">
        <div className="flex flex-col gap-2">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-5/6" />
          <Skeleton className="h-4 w-2/3" />
          <Skeleton className="mt-4 h-24 rounded-lg" />
        </div>
        <Skeleton className="h-[320px] rounded-lg" />
      </div>
    </div>
  );
}

export function StatSkeleton({ count = 4, className }: { count?: number; className?: string }) {
  return (
    <div
      className={cn("bg-border grid grid-cols-2 gap-px overflow-hidden rounded-lg border lg:grid-cols-4", className)}
      aria-hidden
    >
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="bg-card flex flex-col gap-2 px-3 py-2.5">
          <Skeleton className="h-3 w-20" />
          <Skeleton className="h-5 w-24" />
          <Skeleton className="h-2.5 w-28" />
        </div>
      ))}
    </div>
  );
}

export function ListSkeleton({ rows = 10, label = "Loading" }: { rows?: number; label?: string }) {
  return (
    <div className="bg-card overflow-hidden rounded-lg border" aria-busy="true" aria-label={label}>
      <div className="bg-muted/70 flex h-8 items-center border-b px-3">
        <Skeleton className="h-3 w-28" />
      </div>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex h-9 items-center gap-2.5 border-b px-3 last:border-b-0">
          <Skeleton className="size-3.5 rounded-full" />
          <Skeleton className="h-3" style={{ width: `${40 + ((i * 37) % 45)}%` }} />
          <Skeleton className="ml-auto h-3 w-16" />
        </div>
      ))}
    </div>
  );
}
