import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import EmptyState from "@/components/EmptyState/EmptyState";
import GridAndTableViews from "@/components/GridAndTableViews/GridAndTableViews";
import { Badge } from "@/components/ui/badge";
import { listMCPServerInstances } from "@/lib/api";
import { EntityIcon } from "@/lib/entity-icons";
import { mcpAppEntries, type McpAppEntry } from "@/lib/mcp-apps/tools";
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
          <Badge variant="outline" className="text-xs">
            {t("needsInput")}
          </Badge>
        ) : null,
    },
  ];

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title") }],
        description: t("description"),
      }}
    >
      <GridAndTableViews
        searchParams={resolvedSearchParams}
        data={items}
        columns={columns}
        routeChange="/apps"
        itemLink={appLink}
        leftComponent={
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <EntityIcon kind="app" className="text-primary" />
            <span>{items.length}</span>
          </div>
        }
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
              <Badge variant="outline" className="mt-auto w-fit text-xs">
                {t("needsInput")}
              </Badge>
            )}
          </div>
        )}
      />
    </ContentBlock>
  );
}
