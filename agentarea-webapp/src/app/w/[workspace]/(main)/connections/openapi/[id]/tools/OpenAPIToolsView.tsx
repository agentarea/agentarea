"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import ContentBlock from "@/components/ContentBlock";
import EmptyState from "@/components/EmptyState";
import FormError from "@/components/FormError";
import ToolbarRefreshButton from "@/components/ToolbarRefreshButton";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { apiErrorMessage, formatApiError } from "@/lib/api-errors";
import { discoverOpenAPIToolsAction } from "@/lib/server-actions";
import { ToolsTable, ToolsToolbar } from "../../../components/ToolsTable";
import type { OpenAPIConnection } from "../../../types";
import { useToolFacets } from "../../../useToolFacets";

/**
 * The operations the spec exposes as tools, grouped by path. Refreshing
 * re-reads the spec, so it is offered only when the connection has a spec URL.
 */
export default function OpenAPIToolsView({
  connection,
}: {
  connection: OpenAPIConnection;
}) {
  const t = useTranslations("MCPServersPage.openapiDetail");
  const tTools = useTranslations("MCPServersPage.instanceDetail.tools");
  const router = useWorkspaceRouter();
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const tools = connection.available_tools;
  const facets = useToolFacets(tools, null);

  const refresh = async () => {
    if (refreshing) return;
    setRefreshing(true);
    setError(null);
    try {
      const result = await discoverOpenAPIToolsAction(connection.id);
      if (result.error) {
        setError(apiErrorMessage(result, t("errors.discoverFailed")));
        return;
      }
      router.refresh();
    } catch (err) {
      console.error("Failed to refresh OpenAPI tools", err);
      setError(`${t("errors.discoverFailed")}: ${formatApiError(err)}`);
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <ContentBlock
      subheader={
        <ToolsToolbar
          facets={facets}
          controls={
            connection.spec_url ? (
              <ToolbarRefreshButton onRefresh={refresh} refreshing={refreshing} />
            ) : undefined
          }
        />
      }
    >
      <div className="space-y-4">
        {error && <FormError>{error}</FormError>}
        {tools.length > 0 ? (
          <ToolsTable tools={tools} facets={facets} />
        ) : (
          <EmptyState
            title={tTools("noneDiscovered")}
            description={connection.spec_url ? t("noToolsWithSpec") : t("noTools")}
            iconsType="mcp"
            action={
              connection.spec_url
                ? { label: t("refreshFromSpec"), onClick: refresh }
                : undefined
            }
          />
        )}
      </div>
    </ContentBlock>
  );
}
