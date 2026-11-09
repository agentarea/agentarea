import { getTranslations } from "next-intl/server";
import { listAllTools, listClientPlatformToolsets } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";
import { getClientCached } from "../clientData";
import type { McpToolsResult } from "../ToolSelection";
import ClientToolsView from "./ClientToolsView";

export default async function ClientToolsPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const t = await getTranslations("ClientsPage.tools");
  const client = await getClientCached(id);
  const instances = client.mcp_instances ?? [];
  const [catalog, ...instanceTools] = await Promise.all([
    listClientPlatformToolsets(),
    // The tools each instance last reported, without dialing it again.
    ...instances.map((instance) =>
      listAllTools({ include: "mcp", mcpInstanceId: instance.id })
    ),
  ]);
  const mcpTools: Record<string, McpToolsResult> = Object.fromEntries(
    instances.map((instance, i) => {
      const result = instanceTools[i];
      return [
        instance.id,
        result.data
          ? {
              tools: result.data.map((tool) => ({
                name: tool.name,
                description: tool.description,
              })),
            }
          : { error: apiErrorMessage(result, t("mcpToolsFailed")) },
      ];
    })
  );

  return (
    <ClientToolsView
      client={client}
      platformCatalog={catalog.data ?? null}
      catalogError={
        catalog.data ? null : apiErrorMessage(catalog, t("catalogFailed"))
      }
      mcpTools={mcpTools}
    />
  );
}
