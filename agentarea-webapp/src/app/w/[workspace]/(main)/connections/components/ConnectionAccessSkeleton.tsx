import { SectionCard } from "@/components/Overview/OverviewCard";
import {
  CardHeadSkeleton,
  RowSkeleton,
} from "@/components/Overview/OverviewSkeleton";

/** Loading placeholder mirroring a connection's Access tab: one section card. */
export default function ConnectionAccessSkeleton() {
  return (
    <div
      aria-hidden="true"
      className="h-full overflow-y-auto bg-muted/20 px-4 py-5"
    >
      <div className="mx-auto flex w-full max-w-[1120px] flex-col gap-4">
        <SectionCard>
          <CardHeadSkeleton />
          <RowSkeleton titleClassName="h-3 w-64" subClassName="w-32" />
        </SectionCard>
      </div>
    </div>
  );
}
