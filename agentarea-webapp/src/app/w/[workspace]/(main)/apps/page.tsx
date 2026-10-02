import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { cookies } from "next/headers";
import ContentBlock from "@/components/ContentBlock";
import EmptyState from "@/components/EmptyState/EmptyState";
import GridAndTableViews from "@/components/GridAndTableViews/GridAndTableViews";
import { ViewModeTabs } from "@/components/HeaderTabs";
import SubheaderToolbar from "@/components/SubheaderToolbar";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { listMCPServerInstances } from "@/lib/api";
import { mcpAppEntries, type McpAppEntry } from "@/lib/apps/mcp/tools";
import { EntityIcon } from "@/lib/entity-icons";
import { requireApiData } from "@/lib/server-resource";

export const metadata: Metadata = {
  title: "Apps",
};

type AppListItem = McpAppEntry & { id: string };

export default async function AppsPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const t = await getTranslations("AppsPage");
  const resolvedSearchParams = await searchParams;
  // Read tab from URL or fallback to cookie
  const cookieStore = await cookies();
  const cookieTab = cookieStore.get("tab_apps")?.value;
  const tab =
    typeof resolvedSearchParams.tab === "string"
      ? resolvedSearchParams.tab
      : cookieTab || "grid";
  const instances = requireApiData(
    await listMCPServerInstances(),
    "MCP connections"
  );
  const items: AppListItem[] = mcpAppEntries(instances).map((app) => ({
    ...app,
    id: `${app.instanceId}:${app.toolName}`,
  }));

  const appLink = (app: AppListItem) =>
    `/apps/${encodeURIComponent(app.instanceId)}/${encodeURIComponent(app.toolName)}`;

  const columns = [
    {
      header: t("title"),
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
      header: t("connection"),
      accessor: "instanceName",
      render: (value: unknown) => (
        <span className="text-sm text-muted-foreground">{String(value)}</span>
      ),
    },
    {
      header: t("open"),
      accessor: "requiresInput",
      render: (value: unknown) =>
        value ? (
          <StatusIndicator kind="attention" size="sm">
            {t("needsInput")}
          </StatusIndicator>
        ) : null,
    },
  ];

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title") }],
        description: t("description"),
      }}
      subheader={
        <SubheaderToolbar controls={<ViewModeTabs currentTab={tab} />} />
      }
    >
      <GridAndTableViews
        viewMode={tab}
        data={items}
        columns={columns}
        itemLink={appLink}
        emptyState={
          <EmptyState
            title={t("emptyTitle")}
            description={t("emptyDescription")}
            iconsType="mcp"
            action={{ label: t("connectAction"), href: "/connections" }}
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
                {t("needsInput")}
              </StatusIndicator>
            )}
          </div>
        )}
      />
    </ContentBlock>
  );
}
