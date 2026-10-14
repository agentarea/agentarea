"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { RefreshCw } from "lucide-react";
import FormError from "@/components/FormError";
import { EmptyRow, SectionCard } from "@/components/Overview/OverviewCard";
import SectionLoadError from "@/components/SectionLoadError";
import { Button } from "@/components/ui/button";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import type { MCPInstanceConsumer } from "@/lib/api";
import { apiErrorMessage, formatApiError } from "@/lib/api-errors";
import { discoverMCPInstanceToolsAction as discoverMCPInstanceTools } from "@/lib/server-actions";
import { ToolsTable } from "../../components/ToolsTable";
import type { MCPInstance } from "../../types";

type Discovery =
  | { kind: "succeeded"; count: number }
  | { kind: "failed"; message: string }
  | null;

/** The connection's tools, who holds each of them, and a re-discover. */
export default function InstanceToolsView({
  instance,
  consumers,
  consumersError,
}: {
  instance: MCPInstance;
  consumers: MCPInstanceConsumer[] | null;
  consumersError: string | null;
}) {
  const t = useTranslations("MCPServersPage.instanceDetail");
  const router = useWorkspaceRouter();
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [discovery, setDiscovery] = useState<Discovery>(null);

  const tools = (instance.tools ??
    instance.json_spec?.available_tools ??
    []) as Array<{ name: string; description: string }>;

  const handleRefresh = async () => {
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
    <div className="h-full overflow-y-auto px-4 py-5">
      <div className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="note">
            {discovery?.kind === "succeeded"
              ? t("tools.discovered", { count: discovery.count })
              : t("tools.hint")}
          </p>
          <Button
            size="xs"
            variant="outline"
            onClick={handleRefresh}
            isLoading={isRefreshing}
            disabled={isRefreshing}
          >
            {!isRefreshing && <RefreshCw />}
            {tools.length > 0 ? t("tools.refresh") : t("tools.discover")}
          </Button>
        </div>

        {discovery?.kind === "failed" && <FormError>{discovery.message}</FormError>}
        {consumersError && <SectionLoadError message={consumersError} />}

        {tools.length > 0 ? (
          <ToolsTable tools={tools} consumers={consumers} />
        ) : (
          <SectionCard>
            <EmptyRow text={t("tools.noneDiscovered")} />
          </SectionCard>
        )}
      </div>
    </div>
  );
}
