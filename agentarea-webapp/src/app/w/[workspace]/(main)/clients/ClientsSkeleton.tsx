import { useTranslations } from "next-intl";
import ContentBlock from "@/components/ContentBlock";
import { ViewModeTabs } from "@/components/HeaderTabs";
import { CollectionSkeleton } from "@/components/Skeleton";
import SubheaderToolbar from "@/components/SubheaderToolbar";
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
          <Skeleton className="h-5 w-5 shrink-0 rounded-sm motion-reduce:animate-none" />
          <Skeleton className="h-4 w-32 motion-reduce:animate-none" />
        </div>
        <Skeleton className="h-5 w-16 shrink-0 rounded-full motion-reduce:animate-none" />
      </div>
      <div className="space-y-1.5">
        <Skeleton className="h-3.5 w-full motion-reduce:animate-none" />
        <Skeleton className="h-3.5 w-3/4 motion-reduce:animate-none" />
      </div>
      <div className="mt-auto flex items-center gap-3 pt-2">
        <Skeleton className="h-3.5 w-24 motion-reduce:animate-none" />
        <Skeleton className="h-3.5 w-16 motion-reduce:animate-none" />
      </div>
    </div>
  );
}

/** The harness list while it (re)loads, in the view the user picked. */
export function ClientsListSkeleton({ viewMode }: { viewMode?: string }) {
  const t = useTranslations("ClientsPage");

  return (
    <CollectionSkeleton
      viewMode={viewMode}
      // The table columns of ClientsClient.
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

/** The whole page while the harnesses load on the server. */
export default function ClientsSkeleton({ viewMode }: { viewMode?: string }) {
  const t = useTranslations("ClientsPage");

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title") }],
        description: t("description"),
        controls: (
          <Skeleton className="h-6 w-32 motion-reduce:animate-none" />
        ),
      }}
      subheader={
        <SubheaderToolbar controls={<ViewModeTabs currentTab={viewMode} />} />
      }
    >
      <div aria-hidden="true">
        <ClientsListSkeleton viewMode={viewMode} />
      </div>
    </ContentBlock>
  );
}
