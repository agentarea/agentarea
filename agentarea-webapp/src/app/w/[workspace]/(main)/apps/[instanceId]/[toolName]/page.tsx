import { getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";
import { zGetMcpServerInstanceV1McpServerInstancesInstanceIdGetPath } from "@/api/client/zod.gen";
import ContentBlock from "@/components/ContentBlock";
import EntityMark from "@/components/EntityMark";
import { McpAppWorkspace } from "@/components/McpAppFrame";
import WorkspaceLink from "@/components/WorkspaceLink";
import { getMCPServer, getMCPServerInstance } from "@/lib/api";
import { readMcpAppUiResource } from "@/lib/apps/mcp/proxy-client";
import { mcpAppEntries, type McpAppUiResource } from "@/lib/apps/mcp/tools";
import { mcpIdentity } from "@/lib/entity-identity";
import { optionalApiData, requireApiData } from "@/lib/server-resource";
import { getMCPConnectionTitle } from "../../../connections/utils";

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

  // The alert already carries the "could not be loaded" heading; the body
  // says why.
  const [serverSpecResult, resourceResult] = await Promise.all([
    instance.server_spec_id ? getMCPServer(instance.server_spec_id) : null,
    app.requiresInput
      ? null
      : readMcpAppUiResource(app.instanceId, app.resourceUri).then(
          (resource) => ({ resource, error: null }),
          (error: unknown) => ({
            resource: null,
            error: error instanceof Error ? error.message : String(error),
          })
        ),
  ]);
  const resource: McpAppUiResource | null = resourceResult?.resource ?? null;
  const resourceError = resourceResult?.error ?? null;
  const serverSpec =
    serverSpecResult && instance.server_spec_id
      ? optionalApiData(
          serverSpecResult,
          `MCP server ${instance.server_spec_id}`
        )
      : null;
  const connectionTitle = getMCPConnectionTitle(instance, serverSpec);
  const endpointUrl =
    typeof instance.json_spec?.endpoint_url === "string"
      ? instance.json_spec.endpoint_url
      : serverSpec?.remote_url;
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
          <h2 className="truncate text-base font-semibold">{displayTitle}</h2>
          <WorkspaceLink
            href={`/connections/${encodeURIComponent(app.instanceId)}`}
            aria-label={`${t("connection")}: ${connectionTitle}`}
            className="mt-1 inline-flex max-w-full items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
          >
            <EntityMark
              identity={mcpIdentity(instance, serverSpec, endpointUrl)}
              className="h-4 w-4 shrink-0 rounded-[3px]"
            />
            <span className="truncate">{connectionTitle}</span>
          </WorkspaceLink>
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
