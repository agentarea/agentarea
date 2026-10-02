import { useTranslations } from "next-intl";
import { CollectionSkeleton } from "@/components/Skeleton";
import { Skeleton } from "@/components/ui/skeleton";
import { CARD_GRID_LOOSE } from "@/lib/collectionGrids";

// Mirrors the harness card on the Clients page: icon + name with the type
// badge on the right, a 2-line description, then the connection / skill counts.
function ClientCardSkeleton() {
  return (
    <div
      className="card card-shadow flex h-full cursor-default flex-col gap-2 hover:shadow-none"
      aria-hidden="true"
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <Skeleton className="h-5 w-5 shrink-0 rounded-sm" />
          <Skeleton className="h-4 w-32" />
        </div>
        <Skeleton className="h-5 w-16 shrink-0 rounded-full" />
      </div>
      <div className="space-y-1.5">
        <Skeleton className="h-3.5 w-full" />
        <Skeleton className="h-3.5 w-3/4" />
      </div>
      <div className="mt-auto flex items-center gap-3 pt-2">
        <Skeleton className="h-3.5 w-24" />
        <Skeleton className="h-3.5 w-16" />
      </div>
    </div>
  );
}

export default function ClientsSkeleton({ viewMode }: { viewMode?: string }) {
  const t = useTranslations("ClientsPage");

  return (
    <CollectionSkeleton
      viewMode={viewMode}
      // The table columns of the Clients page.
      columns={[
        { header: t("columnHarness"), barClassName: "h-4 w-40" },
        { header: t("type"), barClassName: "h-5 w-16 rounded-full" },
        { header: "MCP", barClassName: "h-4 w-20 rounded-full" },
        { header: t("columnSkills"), barClassName: "h-4 w-20 rounded-full" },
      ]}
      rows={6}
      gridClassName={CARD_GRID_LOOSE}
      count={8}
      Card={ClientCardSkeleton}
    />
  );
}
