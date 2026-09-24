import { getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";
import { zGetMcpServerInstanceV1McpServerInstancesInstanceIdGetPath } from "@/api/client/zod.gen";
import ContentBlock from "@/components/ContentBlock";
import { McpAppWorkspace } from "@/components/McpAppFrame";
import { getMCPServerInstance } from "@/lib/api";
import { readMcpAppUiResource } from "@/lib/mcp-apps/proxy-client";
import { mcpAppEntries, type McpAppUiResource } from "@/lib/mcp-apps/tools";
import { requireApiData } from "@/lib/server-resource";

interface Props {
  params: Promise<{ instanceId: string; toolName: string }>;
}

export default async function McpAppPage({ params }: Props) {
  const { instanceId, toolName } = await params;
  const t = await getTranslations("AppsPage");
  const path =
    zGetMcpServerInstanceV1McpServerInstancesInstanceIdGetPath.safeParse({
      instance_id: instanceId,
    });
  if (!path.success) notFound();
  const instance = requireApiData(
    await getMCPServerInstance(path.data.instance_id),
    "MCP connection"
  );
  const decodedToolName = decodeURIComponent(toolName);
  const app = mcpAppEntries([instance]).find(
    (entry) => entry.toolName === toolName || entry.toolName === decodedToolName
  );
  if (!app) notFound();

  let resource: McpAppUiResource | null = null;
  // The alert already carries the "could not be loaded" heading; the body
  // says why.
  let resourceError: string | null = null;
  if (!app.requiresInput) {
    try {
      resource = await readMcpAppUiResource(app.instanceId, app.resourceUri);
    } catch (error) {
      resourceError = error instanceof Error ? error.message : String(error);
    }
  }
  const displayTitle = app.title || app.toolName;

  return (
    <ContentBlock
      className="p-0 overflow-hidden"
      header={{
        breadcrumb: [
          { label: t("title"), href: "/apps" },
          { label: displayTitle },
        ],
      }}
    >
      <div className="flex h-full min-h-0 flex-col">
        <div className="shrink-0 border-b border-border/70 bg-muted/20 px-4 py-3">
          <h1 className="truncate text-base font-semibold">{displayTitle}</h1>
          <p className="mt-1 text-xs text-muted-foreground">
            {t("connection")}: {app.instanceName}
          </p>
        </div>
        {app.requiresInput ? (
          <div className="flex flex-1 items-center justify-center p-6">
            <div className="max-w-lg rounded-lg border border-border bg-muted/20 p-6 text-center">
              <h2 className="font-semibold">{t("needsInput")}</h2>
              <p className="mt-2 text-sm text-muted-foreground">
                {t("needsInputDescription")}
              </p>
            </div>
          </div>
        ) : resourceError ? (
          <div className="flex flex-1 items-center justify-center p-6">
            <div
              role="alert"
              className="max-w-lg rounded-lg border border-destructive/40 bg-destructive/5 p-6 text-center"
            >
              <h2 className="font-semibold">{t("resourceError")}</h2>
              <p className="mt-2 text-sm text-muted-foreground">
                {resourceError}
              </p>
            </div>
          </div>
        ) : resource ? (
          <McpAppWorkspace
            instanceId={app.instanceId}
            toolName={app.toolName}
            title={displayTitle}
            resource={resource}
          />
        ) : null}
      </div>
    </ContentBlock>
  );
}
