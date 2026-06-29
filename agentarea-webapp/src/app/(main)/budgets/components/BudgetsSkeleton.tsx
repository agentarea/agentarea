import { Skeleton } from "@/components/ui/skeleton";

// Mirrors BudgetsData: a SpendCard + a summary list on top, a cap panel below.
export default function BudgetsSkeleton() {
  return (
    <div className="mx-auto w-full max-w-[980px] space-y-6" aria-hidden="true">
      <div className="grid gap-x-10 gap-y-6 lg:grid-cols-5 lg:divide-x lg:divide-border/50">
        <div className="lg:col-span-3 lg:pr-10">
          <header className="flex items-baseline justify-between">
            <Skeleton className="h-4 w-16" />
            <Skeleton className="h-3 w-24" />
          </header>
          <div className="mt-2 flex items-baseline gap-3">
            <Skeleton className="h-7 w-28" />
            <Skeleton className="h-4 w-12 rounded-full" />
          </div>
          <Skeleton className="mt-3 h-24 w-full rounded" />
        </div>

        <section className="lg:col-span-2 lg:pl-10">
          <Skeleton className="h-4 w-20" />
          <dl className="mt-4 space-y-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <div
                key={i}
                className="flex items-baseline justify-between gap-4 border-b border-border/50 pb-3 last:border-0"
              >
                <Skeleton className="h-3 w-24" />
                <Skeleton className="h-4 w-16" />
              </div>
            ))}
          </dl>
        </section>
      </div>

      <div className="border-t border-border/50 pt-6">
        <Skeleton className="h-28 w-full rounded-lg" />
      </div>
    </div>
  );
}
