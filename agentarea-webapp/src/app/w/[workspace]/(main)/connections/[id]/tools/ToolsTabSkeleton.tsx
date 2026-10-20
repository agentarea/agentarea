import ContentBlock from "@/components/ContentBlock";
import { SectionCard } from "@/components/Overview/OverviewCard";
import { RowSkeleton } from "@/components/Overview/OverviewSkeleton";
import { Skeleton } from "@/components/ui/skeleton";

/** Loading placeholder for the Tools tab: its filter band and a card of rows. */
export default function ToolsTabSkeleton() {
  return (
    <ContentBlock
      subheader={
        <div aria-hidden="true" className="flex flex-1 items-center gap-3">
          <Skeleton className="h-6 w-80" />
          <Skeleton className="h-6 flex-1" />
          <Skeleton className="h-6 w-6" />
        </div>
      }
    >
      <div aria-hidden="true">
        <SectionCard>
          {Array.from({ length: 6 }).map((_, i) => (
            <RowSkeleton key={i} titleClassName="h-3 w-48" subClassName="w-64" />
          ))}
        </SectionCard>
      </div>
    </ContentBlock>
  );
}
