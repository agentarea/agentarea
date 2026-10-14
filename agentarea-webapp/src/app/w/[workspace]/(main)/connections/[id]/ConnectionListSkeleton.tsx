import { SectionCard } from "@/components/Overview/OverviewCard";
import { RowSkeleton } from "@/components/Overview/OverviewSkeleton";

/** Loading placeholder for the Tools and Activity tabs: one card of rows. */
export default function ConnectionListSkeleton() {
  return (
    <div aria-hidden="true" className="h-full overflow-y-auto px-4 py-5">
      <SectionCard>
        {Array.from({ length: 6 }).map((_, i) => (
          <RowSkeleton key={i} titleClassName="h-3 w-48" subClassName="w-64" />
        ))}
      </SectionCard>
    </div>
  );
}
