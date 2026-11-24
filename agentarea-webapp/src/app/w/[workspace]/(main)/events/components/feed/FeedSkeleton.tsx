import { useTranslations } from "next-intl";
import { InfoPanelBody } from "@/components/InfoPanel";
import { TableSkeleton } from "@/components/Skeleton";
import { Skeleton } from "@/components/ui/skeleton";

export function FeedRowsSkeleton({ rows = 12 }: { rows?: number }) {
  const t = useTranslations("EventsPage");
  return (
    // The day's heading, then its table: the same columns as FeedList, the
    // first bar as tall as the source's 28px tile.
    <div className="-mt-2 min-w-0" aria-hidden="true">
      <div className="flex h-9 items-center gap-2 px-1">
        <Skeleton className="h-3.5 w-3.5 rounded-sm" />
        <Skeleton className="h-3 w-16" />
      </div>
      <TableSkeleton
        rows={rows}
        columns={[
          { header: t("feed.kind"), barClassName: "h-7 w-64 rounded-md" },
          {
            header: t("list.stream"),
            headerClassName: "hidden w-[180px] md:table-cell",
            cellClassName: "hidden md:table-cell",
            barClassName: "h-3 w-24",
          },
          {
            header: t("list.result"),
            headerClassName: "w-[180px]",
            barClassName: "h-3 w-16",
          },
        ]}
      />
    </div>
  );
}

export default function FeedSkeleton() {
  return <FeedRowsSkeleton />;
}

/** The side panel while the open event loads: its header, envelope, handlers and body. */
export function FeedEventPanelSkeleton() {
  return (
    <div aria-hidden="true">
      <div className="space-y-2 px-3 py-3">
        <Skeleton className="h-3 w-40" />
        <Skeleton className="h-4 w-56" />
      </div>
      <InfoPanelBody>
        <Skeleton className="h-3 w-20" />
        <div className="grid grid-cols-[4.5rem_minmax(0,1fr)] gap-x-3 gap-y-2.5">
          {["w-24", "w-32", "w-44", "w-40", "w-28"].map((width, i) => (
            <div key={i} className="contents">
              <Skeleton className="h-3.5 w-14" />
              <Skeleton className={`h-3.5 ${width}`} />
            </div>
          ))}
        </div>
        <div className="space-y-2">
          <Skeleton className="h-3 w-20" />
          <Skeleton className="h-16 w-full rounded-md" />
        </div>
        <div className="space-y-2">
          <Skeleton className="h-3 w-16" />
          <Skeleton className="h-40 w-full rounded-md" />
        </div>
      </InfoPanelBody>
    </div>
  );
}
