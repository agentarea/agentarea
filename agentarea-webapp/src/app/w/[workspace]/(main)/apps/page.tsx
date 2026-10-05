import { Suspense } from "react";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { cookies } from "next/headers";
import type { McpServerInstanceResponse } from "@/api/client/types.gen";
import ContentBlock from "@/components/ContentBlock";
import EmptyState from "@/components/EmptyState/EmptyState";
import GridAndTableViews from "@/components/GridAndTableViews/GridAndTableViews";
import { ViewModeTabs } from "@/components/HeaderTabs";
import { CollectionSkeleton, type SkeletonColumn } from "@/components/Skeleton";
import SubheaderToolbar from "@/components/SubheaderToolbar";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusIndicator } from "@/components/ui/status-indicator";
import type { ApiResultLike } from "@/lib/api-errors";
import { listMCPServerInstances } from "@/lib/api";
import { mcpAppEntries, type McpAppEntry } from "@/lib/apps/mcp/tools";
import { EntityIcon } from "@/lib/entity-icons";
import { requireApiData } from "@/lib/server-resource";

export const metadata: Metadata = {
  title: "Apps",
};

const APPS_GRID_CLASS =
  "grid grid-cols-1 gap-[12px] md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5";

type AppSearchParams = { [key: string]: string | string[] | undefined };
type AppListItem = McpAppEntry & { id: string };
type AppsInstancesResult = Promise<
  | { apiResult: ApiResultLike<McpServerInstanceResponse[]> }
  | { exception: unknown }
>;

type AppsLabels = {
  title: string;
  description: string;
  connection: string;
  open: string;
  needsInput: string;
  emptyTitle: string;
  emptyDescription: string;
  connectAction: string;
};

function AppCardSkeleton() {
  return (
    <div className="card card-shadow group flex min-h-[150px] flex-col gap-3 p-4">
      <div className="flex items-start gap-2">
        <Skeleton className="mt-0.5 h-5 w-5 shrink-0 rounded-full motion-reduce:animate-none" />
        <div className="min-w-0 flex-1 space-y-2">
          <Skeleton className="h-4 w-3/4 motion-reduce:animate-none" />
          <Skeleton className="h-3 w-1/2 motion-reduce:animate-none" />
        </div>
      </div>
      <Skeleton className="h-3 w-full motion-reduce:animate-none" />
      <Skeleton className="h-3 w-4/5 motion-reduce:animate-none" />
    </div>
  );
}

function AppsListSkeleton({
  viewMode,
  columns,
}: {
  viewMode: string;
  columns: SkeletonColumn[];
}) {
  return (
    <div aria-hidden="true">
      <CollectionSkeleton
        viewMode={viewMode}
        columns={columns}
        rows={8}
        gridClassName={APPS_GRID_CLASS}
        count={10}
        Card={AppCardSkeleton}
      />
    </div>
  );
}

async function AppsList({
  instancesPromise,
  viewMode,
  labels,
}: {
  instancesPromise: AppsInstancesResult;
  viewMode: string;
  labels: AppsLabels;
}) {
  const result = await instancesPromise;
  if ("exception" in result) throw result.exception;
  const instances = requireApiData(result.apiResult, "MCP connections");
  const items: AppListItem[] = mcpAppEntries(instances).map((app) => ({
    ...app,
    id: `${app.instanceId}:${app.toolName}`,
  }));

  const appLink = (app: AppListItem) =>
    `/apps/${encodeURIComponent(app.instanceId)}/${encodeURIComponent(app.toolName)}`;

  const columns = [
    {
      header: labels.title,
      accessor: "title",
      render: (_value: unknown, app: AppListItem) => (
        <div className="flex items-start gap-2">
          <EntityIcon kind="app" className="mt-0.5 shrink-0 text-primary" />
          <div className="min-w-0">
            <div className="font-medium">{app.title || app.toolName}</div>
            <div className="mt-1 line-clamp-2 max-w-xl text-xs text-muted-foreground">
              {app.description}
            </div>
          </div>
        </div>
      ),
      cellClassName: "font-medium",
    },
    {
      header: labels.connection,
      accessor: "instanceName",
      render: (value: unknown) => (
        <span className="text-sm text-muted-foreground">{String(value)}</span>
      ),
    },
    {
      header: labels.open,
      accessor: "requiresInput",
      render: (value: unknown) =>
        value ? (
          <StatusIndicator kind="attention" size="sm">
            {labels.needsInput}
          </StatusIndicator>
        ) : null,
    },
  ];

  return (
    <GridAndTableViews
      viewMode={viewMode}
      data={items}
      columns={columns}
      gridClassName={APPS_GRID_CLASS}
      itemLink={appLink}
      emptyState={
        <EmptyState
          title={labels.emptyTitle}
          description={labels.emptyDescription}
          iconsType="mcp"
          action={{ label: labels.connectAction, href: "/connections" }}
        />
      }
      cardContent={(app) => (
        <div className="flex min-h-[150px] flex-col gap-3">
          <div className="flex items-start gap-2">
            <EntityIcon kind="app" className="mt-0.5 shrink-0 text-primary" />
            <div className="min-w-0">
              <div className="truncate text-[16px] font-medium">
                {app.title || app.toolName}
              </div>
              <div className="mt-1 truncate text-xs text-muted-foreground">
                {app.instanceName}
              </div>
            </div>
          </div>
          <p className="line-clamp-4 text-sm text-muted-foreground">
            {app.description}
          </p>
          {app.requiresInput && (
            <StatusIndicator kind="attention" size="sm" className="mt-auto">
              {labels.needsInput}
            </StatusIndicator>
          )}
        </div>
      )}
    />
  );
}

export default async function AppsPage({
  searchParams,
}: {
  searchParams: Promise<AppSearchParams>;
}) {
  const instancesPromise = listMCPServerInstances().then(
    (apiResult) => ({ apiResult }),
    (exception: unknown) => ({ exception })
  );
  const [t, resolvedSearchParams, cookieStore] = await Promise.all([
    getTranslations("AppsPage"),
    searchParams,
    cookies(),
  ]);
  // Read tab from URL or fallback to cookie
  const viewMode =
    typeof resolvedSearchParams.tab === "string"
      ? resolvedSearchParams.tab
      : cookieStore.get("tab_apps")?.value || "grid";
  const labels: AppsLabels = {
    title: t("title"),
    description: t("description"),
    connection: t("connection"),
    open: t("open"),
    needsInput: t("needsInput"),
    emptyTitle: t("emptyTitle"),
    emptyDescription: t("emptyDescription"),
    connectAction: t("connectAction"),
  };
  const skeletonColumns: SkeletonColumn[] = [
    {
      header: labels.title,
      barClassName: "h-7 w-48 motion-reduce:animate-none",
    },
    {
      header: labels.connection,
      barClassName: "w-28 motion-reduce:animate-none",
    },
    { header: labels.open, barClassName: "w-20 motion-reduce:animate-none" },
  ];

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: labels.title }],
        description: labels.description,
      }}
      subheader={
        <SubheaderToolbar controls={<ViewModeTabs currentTab={viewMode} />} />
      }
    >
      <Suspense
        fallback={
          <AppsListSkeleton viewMode={viewMode} columns={skeletonColumns} />
        }
      >
        <AppsList
          instancesPromise={instancesPromise}
          viewMode={viewMode}
          labels={labels}
        />
      </Suspense>
    </ContentBlock>
  );
}
