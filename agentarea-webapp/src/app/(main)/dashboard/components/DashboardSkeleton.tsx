import { Skeleton } from "@/components/ui/skeleton";

// Section titles are static, so we keep them real and skeleton only the
// right-aligned metadata + body — mirroring DashboardData's two-row layout.
function SectionHeader({ title }: { title: string }) {
  return (
    <header className="flex items-baseline justify-between">
      <h3 className="text-[13px] font-medium text-foreground">{title}</h3>
      <Skeleton className="h-3 w-20" />
    </header>
  );
}

function SpendSkeleton() {
  return (
    <section>
      <SectionHeader title="Spend" />
      <div className="mt-2 flex items-baseline gap-3">
        <Skeleton className="h-7 w-28" />
        <Skeleton className="h-4 w-12 rounded-full" />
        <div className="ml-auto flex flex-col items-end gap-1">
          <Skeleton className="h-3 w-16" />
          <Skeleton className="h-3 w-20" />
        </div>
      </div>
      <Skeleton className="mt-3 h-24 w-full rounded" />
    </section>
  );
}

function ActivitySkeleton() {
  return (
    <section>
      <SectionHeader title="Activity" />
      <div className="mt-3 grid grid-cols-3 gap-6">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i}>
            <Skeleton className="h-3 w-16" />
            <Skeleton className="mt-1 h-6 w-12" />
            <Skeleton className="mt-1.5 h-6 w-full" />
          </div>
        ))}
      </div>
    </section>
  );
}

function AgentRowsSkeleton() {
  return (
    <section>
      <SectionHeader title="Agents" />
      <ul className="-mx-2 mt-2 divide-y divide-border/50">
        {Array.from({ length: 5 }).map((_, i) => (
          <li key={i}>
            <div className="flex items-center gap-3 px-2 py-2.5">
              <Skeleton className="h-6 w-6 shrink-0 rounded-md" />
              <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                <Skeleton className="h-3 w-32" />
                <Skeleton className="h-3 w-48" />
              </div>
              <div className="hidden shrink-0 gap-5 sm:flex">
                <Skeleton className="h-6 w-8" />
                <Skeleton className="h-6 w-8" />
                <Skeleton className="h-6 w-10" />
              </div>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

function BlockersSkeleton() {
  return (
    <section>
      <SectionHeader title="Blockers" />
      <div className="mt-3 space-y-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-10 w-full rounded" />
        ))}
      </div>
    </section>
  );
}

export default function DashboardSkeleton() {
  return (
    <div aria-hidden="true">
      <div className="grid gap-x-10 gap-y-6 lg:grid-cols-5 lg:divide-x lg:divide-border/50">
        <div className="lg:col-span-3 lg:pr-10">
          <SpendSkeleton />
        </div>
        <div className="lg:col-span-2 lg:pl-10">
          <ActivitySkeleton />
        </div>
      </div>

      <div className="my-6 border-t border-border/50" />

      <div className="grid gap-x-10 gap-y-6 lg:grid-cols-3 lg:divide-x lg:divide-border/50">
        <div className="lg:col-span-2 lg:pr-10">
          <AgentRowsSkeleton />
        </div>
        <div className="lg:col-span-1 lg:pl-10">
          <BlockersSkeleton />
        </div>
      </div>
    </div>
  );
}
