"use client";

import { useCallback, useOptimistic, useState, useTransition } from "react";
import { useTranslations } from "next-intl";
import ContentBlock from "@/components/ContentBlock";
import EmptyState from "@/components/EmptyState";
import FormError from "@/components/FormError";
import SectionLoadError from "@/components/SectionLoadError";
import ToolbarRefreshButton from "@/components/ToolbarRefreshButton";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import type { MCPInstanceConsumer } from "@/lib/api";
import { apiErrorMessage, formatApiError } from "@/lib/api-errors";
import { discoverMCPInstanceToolsAction as discoverMCPInstanceTools } from "@/lib/server-actions";
import { ToolsTable, ToolsToolbar } from "../../components/ToolsTable";
import {
  sharedToolPolicy,
  withDefault,
  type ToolPolicy,
  type ToolPolicyState,
} from "../../tool-policy";
import type { MCPInstance } from "../../types";
import { useToolFacets } from "../../useToolFacets";
import { setToolPoliciesAction } from "../actions";
import type { ToolPoliciesResult } from "../toolPolicyData";
import { ToolPolicySelect } from "./ToolPolicySelect";

const ALLOWED: ToolPolicyState = {
  default: "allow",
  effective: "allow",
  reason: null,
};

type Discovery =
  | { kind: "succeeded"; count: number }
  | { kind: "failed"; message: string }
  | null;

/**
 * The connection's tools, the workspace default policy of each (set by an
 * admin, read by everyone), who holds them, and a re-discover.
 */
export default function InstanceToolsView({
  instance,
  consumers,
  consumersError,
  toolPolicies,
}: {
  instance: MCPInstance;
  consumers: MCPInstanceConsumer[] | null;
  consumersError: string | null;
  toolPolicies: ToolPoliciesResult;
}) {
  const t = useTranslations("MCPServersPage.instanceDetail");
  const router = useWorkspaceRouter();
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [discovery, setDiscovery] = useState<Discovery>(null);
  const [policyError, setPolicyError] = useState<string | null>(null);

  const tools = (instance.tools ??
    instance.json_spec?.available_tools ??
    []) as Array<{ name: string; description: string }>;
  const [policies, showPolicies] = useOptimistic(
    toolPolicies.policies ?? {},
    (current, change: { names: string[]; policy: ToolPolicy }) => ({
      ...current,
      ...Object.fromEntries(
        change.names.map((name) => [
          name,
          withDefault(current[name] ?? ALLOWED, change.policy),
        ])
      ),
    })
  );
  const [, startPolicyChange] = useTransition();
  const hasPolicies = toolPolicies.policies !== null;
  const stateOf = (toolName: string) => policies[toolName] ?? ALLOWED;
  // The filters count what the engine does, not only what is set here.
  const policyOf = useCallback(
    (toolName: string): ToolPolicy => policies[toolName]?.effective ?? "allow",
    [policies]
  );
  const facets = useToolFacets(tools, consumers, hasPolicies ? policyOf : null);

  const setPolicy = (names: string[], policy: ToolPolicy) =>
    startPolicyChange(async () => {
      showPolicies({ names, policy });
      setPolicyError(null);
      try {
        const result = await setToolPoliciesAction(instance.id, names, policy);
        if (!result.ok) setPolicyError(result.error);
      } catch (err) {
        console.error("Failed to set tool policies", err);
        setPolicyError(
          `${t("tools.policy.saveFailed")}: ${formatApiError(err)}`
        );
      }
    });

  const policyControls = hasPolicies
    ? {
        cell: (toolName: string) => (
          <ToolPolicySelect
            label={t("tools.policy.label")}
            value={stateOf(toolName).default}
            effective={stateOf(toolName)}
            onChange={
              toolPolicies.canEdit
                ? (policy) => setPolicy([toolName], policy)
                : undefined
            }
          />
        ),
        group: toolPolicies.canEdit
          ? (toolNames: string[]) => (
              <ToolPolicySelect
                label={t("tools.policy.groupLabel")}
                prefix={t("tools.policy.allPrefix")}
                value={sharedToolPolicy(policies, toolNames)}
                onChange={(policy) => setPolicy(toolNames, policy)}
              />
            )
          : null,
      }
    : null;

  const handleRefresh = async () => {
    if (isRefreshing) return;
    setIsRefreshing(true);
    setDiscovery(null);
    try {
      const response = await discoverMCPInstanceTools(instance.id);
      if (response.error) {
        setDiscovery({
          kind: "failed",
          message: apiErrorMessage(response, t("tools.discoverFailed")),
        });
        return;
      }
      // The endpoint returns 200 with {tools, verification} even when verification
      // failed, so report based on the actual result, not the HTTP status.
      const result = response.data as
        | {
            tools?: unknown[];
            verification?: { status?: string; error?: { message?: string } };
          }
        | undefined;
      if (result?.verification?.status === "succeeded") {
        setDiscovery({ kind: "succeeded", count: result.tools?.length ?? 0 });
      } else {
        const reason = result?.verification?.error?.message;
        setDiscovery({
          kind: "failed",
          message: reason
            ? `${t("tools.discoverFailed")}: ${reason}`
            : t("tools.discoverUnverified"),
        });
      }
      router.refresh();
    } catch (err) {
      console.error("Failed to discover MCP instance tools", err);
      setDiscovery({
        kind: "failed",
        message: `${t("tools.discoverFailed")}: ${formatApiError(err)}`,
      });
    } finally {
      setIsRefreshing(false);
    }
  };

  return (
    <ContentBlock
      subheader={
        <ToolsToolbar
          facets={facets}
          controls={
            <ToolbarRefreshButton
              onRefresh={handleRefresh}
              refreshing={isRefreshing}
            />
          }
        />
      }
    >
      <div className="space-y-4">
        {discovery?.kind === "failed" && (
          <FormError>{discovery.message}</FormError>
        )}
        {discovery?.kind === "succeeded" && (
          <p className="note" role="status">
            {t("tools.discovered", { count: discovery.count })}
          </p>
        )}
        {consumersError && <SectionLoadError message={consumersError} />}
        {toolPolicies.error && (
          <SectionLoadError message={toolPolicies.error} />
        )}
        {policyError && <FormError>{policyError}</FormError>}
        {hasPolicies && tools.length > 0 && (
          <p className="note">
            {toolPolicies.canEdit
              ? t("tools.policy.scope")
              : `${t("tools.policy.scope")} ${t("tools.policy.adminOnly")}`}
          </p>
        )}

        {tools.length > 0 ? (
          <ToolsTable
            tools={tools}
            consumers={consumers}
            facets={facets}
            policy={policyControls}
          />
        ) : (
          <EmptyState
            title={t("tools.noneDiscovered")}
            description={t("tools.noneDescription")}
            iconsType="mcp"
            action={{ label: t("tools.discover"), onClick: handleRefresh }}
          />
        )}
      </div>
    </ContentBlock>
  );
}
