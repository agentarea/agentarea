import { Suspense } from "react";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { cookies } from "next/headers";
import type { McpServerInstanceResponse } from "@/api/client/types.gen";
import ContentBlock from "@/components/ContentBlock";
import EmptyState from "@/components/EmptyState/EmptyState";
import EntityMark from "@/components/EntityMark";
import GridAndTableViews from "@/components/GridAndTableViews/GridAndTableViews";
import { ViewModeTabs } from "@/components/HeaderTabs";
import LinkedCard from "@/components/LinkedCard/LinkedCard";
import {
  CollectionSkeleton,
  LinkedCardSkeleton,
  type SkeletonColumn,
} from "@/components/Skeleton";
import SubheaderToolbar from "@/components/SubheaderToolbar";
import { getMCPServer, listMCPServerInstances } from "@/lib/api";
import type { ApiResultLike } from "@/lib/api-errors";
import { mcpAppEntries, type McpAppEntry } from "@/lib/apps/mcp/tools";
import { mcpIdentity, type EntityIdentity } from "@/lib/entity-identity";
import { optionalApiData, requireApiData } from "@/lib/server-resource";
import { getMCPConnectionTitle } from "../connections/utils";

export const metadata: Metadata = {
  title: "Apps",
};

const APPS_GRID_CLASS =
  "grid grid-cols-1 gap-[12px] md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5";

type AppSearchParams = { [key: string]: string | string[] | undefined };
type AppListItem = McpAppEntry & {
  id: string;
  connectionTitle: string;
  connectionIdentity: EntityIdentity;
};
type AppsInstancesResult = Promise<
  | { apiResult: ApiResultLike<McpServerInstanceResponse[]> }
  | { exception: unknown }
>;

type AppsLabels = {
  title: string;
  description: string;
  connection: string;
  emptyTitle: string;
  emptyDescription: string;
  connectAction: string;
};

function AppCardSkeleton() {
  return <LinkedCardSkeleton icon subtitle lines={2} />;
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
  const apps = mcpAppEntries(instances).filter((app) => !app.requiresInput);
  const instanceById = new Map(instances.map((i) => [i.id, i]));
  const specIds = [
    ...new Set(
      apps.flatMap(
        (app) => instanceById.get(app.instanceId)?.server_spec_id ?? []
      )
    ),
  ];
  const specs = new Map(
    await Promise.all(
      specIds.map(
        async (id) =>
          [
            id,
            optionalApiData(await getMCPServer(id), `MCP server ${id}`),
          ] as const
      )
    )
  );
  const items: AppListItem[] = apps.map((app) => {
    const instance = instanceById.get(app.instanceId);
    const spec = instance?.server_spec_id
      ? specs.get(instance.server_spec_id)
      : null;
    return {
      ...app,
      id: `${app.instanceId}:${app.toolName}`,
      connectionTitle: instance
        ? getMCPConnectionTitle(instance, spec)
        : app.instanceName,
      connectionIdentity: mcpIdentity(instance ?? {}, spec),
    };
  });

  const appLink = (app: AppListItem) =>
    `/apps/${encodeURIComponent(app.instanceId)}/${encodeURIComponent(app.toolName)}`;

  const columns = [
    {
      header: labels.title,
      accessor: "title",
      render: (_value: unknown, app: AppListItem) => (
        <div className="flex items-start gap-2">
          <EntityMark
            identity={app.connectionIdentity}
            className="mt-0.5 h-5 w-5 shrink-0 rounded-md"
          />
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
      accessor: "connectionTitle",
      render: (value: unknown) => (
        <span className="text-sm text-muted-foreground">{String(value)}</span>
      ),
    },
  ];

  return (
    <GridAndTableViews
      viewMode={viewMode}
      data={items}
      columns={columns}
      gridClassName={APPS_GRID_CLASS}
      itemLink={appLink}
      wrapCardContent={false}
      emptyState={
        <EmptyState
          title={labels.emptyTitle}
          description={labels.emptyDescription}
          iconsType="mcp"
          action={{ label: labels.connectAction, href: "/connections" }}
        />
      }
      cardContent={(app) => (
        <LinkedCard
          href={appLink(app)}
          title={app.title || app.toolName}
          icon={
            <EntityMark
              identity={app.connectionIdentity}
              className="h-6 w-6 rounded-md"
            />
          }
          subtitle={
            <span className="truncate text-xs">{app.connectionTitle}</span>
          }
        >
          {app.description && (
            <p className="line-clamp-3 text-sm text-muted-foreground">
              {app.description}
            </p>
          )}
        </LinkedCard>
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
