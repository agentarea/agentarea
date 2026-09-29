import { Skeleton } from "@/components/ui/skeleton";

// Mirrors SkillsCard: tile + name, two-line description, source/scope footer.
function SkillCardSkeleton() {
  return (
    <div className="rounded-[10px] border border-zinc-200 bg-background p-3.5 dark:border-zinc-800">
      <div className="mb-[9px] flex items-center gap-[9px]">
        <Skeleton className="h-[30px] w-[30px] rounded-[8px]" />
        <Skeleton className="h-4 w-2/3" />
      </div>
      <div className="mb-3 space-y-1.5">
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-4/5" />
      </div>
      <div className="flex items-center gap-2">
        <Skeleton className="h-[22px] w-20 rounded-full" />
        <Skeleton className="h-3 w-16" />
      </div>
    </div>
  );
}

// Mirrors SkillRow (InteractiveListRow): tile + name + description + badges.
function SkillRowSkeleton() {
  return (
    <div className="flex items-center gap-3 border-b border-zinc-200 px-4 py-2.5 dark:border-zinc-700">
      <Skeleton className="h-[22px] w-[22px] shrink-0 rounded-[6px]" />
      <Skeleton className="h-3.5 w-40 shrink-0" />
      <Skeleton className="h-3 flex-1" />
      <Skeleton className="hidden h-[22px] w-20 shrink-0 rounded-full sm:block" />
      <Skeleton className="hidden h-3 w-12 shrink-0 sm:block" />
    </div>
  );
}

export default function SkillsContentSkeleton({ view }: { view: "list" | "grid" }) {
  if (view === "grid") {
    return (
      <div
        className="grid gap-3 p-4"
        style={{ gridTemplateColumns: "repeat(auto-fill, minmax(264px, 1fr))" }}
        aria-hidden="true"
      >
        {Array.from({ length: 12 }).map((_, i) => (
          <SkillCardSkeleton key={i} />
        ))}
      </div>
    );
  }
  return (
    <div aria-hidden="true">
      {Array.from({ length: 12 }).map((_, i) => (
        <SkillRowSkeleton key={i} />
      ))}
    </div>
  );
}
