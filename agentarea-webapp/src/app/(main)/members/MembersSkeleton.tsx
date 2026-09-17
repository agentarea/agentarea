import { Skeleton } from "@/components/ui/skeleton";

// One section: a title/description header + a bordered table of placeholder rows.
function SectionSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <section className="space-y-3">
      <div className="space-y-1.5">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-3 w-64" />
      </div>
      <div className="overflow-hidden rounded-md border bg-white dark:bg-zinc-900">
        {Array.from({ length: rows }).map((_, i) => (
          <div
            key={i}
            className="flex items-center justify-between gap-4 border-b px-3 py-3 last:border-0"
          >
            <div className="flex min-w-0 flex-col gap-1.5">
              <Skeleton className="h-4 w-40" />
              <Skeleton className="h-3 w-24" />
            </div>
            <Skeleton className="h-3 w-24" />
            <Skeleton className="h-7 w-16 rounded-md" />
          </div>
        ))}
      </div>
    </section>
  );
}

export default function MembersSkeleton() {
  return (
    <div className="space-y-8" aria-hidden="true">
      <SectionSkeleton rows={5} />
      {/* Most workspaces have no pending invitations, and that section then
          renders as a single line — matching it here avoids a layout jump. */}
      <Skeleton className="h-4 w-48" />
    </div>
  );
}
