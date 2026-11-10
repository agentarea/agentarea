"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import ContentBlock from "@/components/ContentBlock";
import EmptyState from "@/components/EmptyState";
import FormError from "@/components/FormError";
import SectionLoadError from "@/components/SectionLoadError";
import ToolbarRefreshButton from "@/components/ToolbarRefreshButton";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { apiErrorMessage, formatApiError } from "@/lib/api-errors";
import { discoverOpenAPIToolsAction } from "@/lib/server-actions";
import { ToolsTable, ToolsToolbar } from "../../../components/ToolsTable";
import type { ToolPoliciesResult } from "../../../toolPolicyData";
import type { OpenAPIConnection } from "../../../types";
import { useToolFacets } from "../../../useToolFacets";
import { useToolPolicyControls } from "../../../useToolPolicyControls";
import { setOpenAPIToolPoliciesAction } from "../actions";

/**
 * The operations the spec exposes as tools, grouped by path, with the workspace
 * default policy of each (set by an admin, read by everyone). Refreshing
 * re-reads the spec, so it is offered only when the connection has a spec URL.
 */
export default function OpenAPIToolsView({
  connection,
  toolPolicies,
}: {
  connection: OpenAPIConnection;
  toolPolicies: ToolPoliciesResult;
}) {
  const t = useTranslations("MCPServersPage.openapiDetail");
  const tTools = useTranslations("MCPServersPage.instanceDetail.tools");
  const router = useWorkspaceRouter();
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const tools = connection.available_tools;
  const policy = useToolPolicyControls(toolPolicies, (names, value) =>
    setOpenAPIToolPoliciesAction(connection.id, names, value)
  );
  const facets = useToolFacets(tools, null, policy.policyOf);

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
              <ToolbarRefreshButton
                onRefresh={refresh}
                refreshing={refreshing}
              />
            ) : undefined
          }
        />
      }
    >
      <div className="space-y-4">
        {error && <FormError>{error}</FormError>}
        {toolPolicies.error && (
          <SectionLoadError message={toolPolicies.error} />
        )}
        {policy.error && <FormError>{policy.error}</FormError>}
        {policy.controls && tools.length > 0 && !toolPolicies.canEdit && (
          <p className="note">{tTools("policy.adminOnly")}</p>
        )}
        {tools.length > 0 ? (
          <ToolsTable tools={tools} facets={facets} policy={policy.controls} />
        ) : (
          <EmptyState
            title={tTools("noneDiscovered")}
            description={
              connection.spec_url ? t("noToolsWithSpec") : t("noTools")
            }
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
