import { SectionCard } from "@/components/Overview/OverviewCard";
import {
  CardHeadSkeleton,
  RowSkeleton,
} from "@/components/Overview/OverviewSkeleton";

/** Loading placeholder mirroring a connection's Settings tab: a column of section cards. */
export default function ConnectionSettingsSkeleton() {
  return (
    <div
      aria-hidden="true"
      className="h-full overflow-y-auto bg-muted/20 px-4 py-5"
    >
      <div className="mx-auto flex w-full max-w-[1120px] flex-col gap-4">
        {[1, 2, 2, 1].map((rows, i) => (
          <SectionCard key={i}>
            <CardHeadSkeleton />
            {Array.from({ length: rows }).map((_, j) => (
              <RowSkeleton
                key={j}
                titleClassName="h-3 w-40"
                subClassName="w-24"
              />
            ))}
          </SectionCard>
        ))}
      </div>
    </div>
  );
}
