import { useTranslations } from "next-intl";
import { InfoPanelBody } from "@/components/InfoPanel";
import { TableSkeleton } from "@/components/Skeleton";
import { Skeleton } from "@/components/ui/skeleton";

/** The feed's columns: the filter rail and the rows. */
export const FEED_GRID =
  "grid gap-6 lg:grid-cols-[200px_minmax(0,1fr)] xl:gap-8";

export function FeedRailSkeleton() {
  return (
    <div className="hidden space-y-5 lg:block" aria-hidden="true">
      {[4, 3, 6].map((rows, section) => (
        <div key={section} className="space-y-2">
          <Skeleton className="h-3 w-16" />
          {Array.from({ length: rows }, (_, i) => (
            <Skeleton key={i} className="h-5 w-full" />
          ))}
        </div>
      ))}
    </div>
  );
}

export function FeedRowsSkeleton({ rows = 12 }: { rows?: number }) {
  const t = useTranslations("EventsPage");
  return (
    <div className="min-w-0" aria-hidden="true">
      <Skeleton className="mb-2 h-3 w-14" />
      <TableSkeleton
        rows={rows}
        columns={[
          { header: t("feed.received"), barClassName: "h-3 w-10" },
          { header: t("feed.kind"), barClassName: "h-3 w-48" },
          {
            header: t("list.stream"),
            headerClassName: "hidden md:table-cell",
            cellClassName: "hidden md:table-cell",
            barClassName: "h-3 w-20",
          },
          { header: t("list.result"), barClassName: "h-3 w-12" },
        ]}
      />
    </div>
  );
}

export default function FeedSkeleton() {
  return (
    <>
      <FeedRailSkeleton />
      <FeedRowsSkeleton />
    </>
  );
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
