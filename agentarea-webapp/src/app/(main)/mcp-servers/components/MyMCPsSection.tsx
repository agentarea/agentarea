"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import CatalogSuggestions from "@/components/CatalogSuggestions";
import EmptyState from "@/components/EmptyState";
import Table from "@/components/Table/Table";
import { Badge } from "@/components/ui/badge";
import { StatusIndicator } from "@/components/ui/status-indicator";
import {
  getMcpHealthStatusPresentation,
  getOpenApiConnectionDisplayStatus,
} from "@/lib/status";
import { getMCPHealthStatusAction as getMCPHealthStatus } from "@/lib/server-actions";
import {
  HealthCheck,
  HealthStatus,
  MCPInstance,
  MCPServer,
  OpenAPIConnection,
} from "../types";
import {
  getEffectiveMCPVerificationStatus,
  getMCPConnectionIconSrc,
  getMCPInstanceToolCount,
  MCP_CONSTANTS,
} from "../utils";
import {
  MCPInstanceCard,
  OpenAPIConnectionCard,
  OpenAPIConnectionMark,
} from "./MCPCard";

// Strip noisy provenance tails (e.g. "… OAuth status: needs_verification.")
// from registry-sourced descriptions so the cell reads cleanly.
function cleanDescription(value?: string | null): string {
  if (!value) return "";
  return value
    .split(/\.?\s*OAuth status:/i)[0]
    .replace(/\s+/g, " ")
    .trim();
}

function hostOf(url?: string | null): string {
  if (!url) return "";
  try {
    return new URL(url).host;
  } catch {
    return url.replace(/^https?:\/\//, "").split("/")[0];
  }
}

interface MyMCPsSectionProps {
  mcpInstances: MCPInstance[];
  mcpServers: MCPServer[];
  openApiConnections?: OpenAPIConnection[];
  viewMode?: string;
  searchQuery?: string;
  hasNoData?: boolean;
}

export function MyMCPsSection({
  mcpInstances,
  mcpServers,
  openApiConnections = [],
  viewMode = "grid",
  searchQuery = "",
  hasNoData = false,
}: MyMCPsSectionProps) {
  const t = useTranslations("MCPServersPage");
  const router = useRouter();
  const [healthChecks, setHealthChecks] = useState<HealthCheck[]>([]);
  const [healthLoading, setHealthLoading] = useState(true);

  // Health status polling
  useEffect(() => {
    const fetchHealthStatus = async () => {
      try {
        const healthData = await getMCPHealthStatus();
        setHealthChecks(healthData.health_checks);
      } catch (error) {
        console.error("Failed to fetch health status:", error);
      } finally {
        setHealthLoading(false);
      }
    };

    fetchHealthStatus();
    const interval = setInterval(
      fetchHealthStatus,
      MCP_CONSTANTS.HEALTH_CHECK_INTERVAL_MS
    );
    return () => clearInterval(interval);
  }, []);

  // Get health check for instance
  const getHealthCheck = (instanceName: string): HealthCheck | undefined => {
    let healthCheck = healthChecks.find(
      (check) => check.service_name === instanceName
    );

    if (!healthCheck) {
      const normalizedInstanceName = instanceName
        .toLowerCase()
        .replace(/\s+/g, "-")
        .replace(/[^a-z0-9-]/g, "");

      healthCheck = healthChecks.find(
        (check) =>
          check.service_name === normalizedInstanceName ||
          check.service_name.includes(normalizedInstanceName) ||
          normalizedInstanceName.includes(check.service_name)
      );
    }

    return healthCheck;
  };

  const STATUS_TO_HEALTH: Record<string, HealthStatus> = {
    connected: "connected",
    succeeded: "connected",
    running: "healthy",
    failed: "unhealthy",
    stopped: "unknown",
    pending: "starting",
    starting: "starting",
  };

  // Get health status for instance
  const getHealthStatus = (instance: MCPInstance): HealthStatus => {
    const instanceType = (instance.json_spec?.type as string) || "docker";
    const vStatus = getEffectiveMCPVerificationStatus(instance);

    // URL-type and bundle have no container health checks — map verification status directly
    if (instanceType === "url" || instanceType === "bundle") {
      const vToHealth: Record<string, HealthStatus> = {
        succeeded: "connected",
        in_progress: "starting",
        failed: "unhealthy",
        never_attempted: "unknown",
      };
      return vToHealth[vStatus] ?? "unknown";
    }

    const healthCheck = getHealthCheck(instance.name);

    if (healthLoading) return "unknown";
    if (!healthCheck) return "unknown";
    if (healthCheck.healthy && healthCheck.http_reachable) return "healthy";
    if (!healthCheck.http_reachable) return "starting";
    return "unhealthy";
  };

  const getOpenAPIHealthStatus = (
    connection: OpenAPIConnection
  ): HealthStatus => {
    const displayStatus = getOpenApiConnectionDisplayStatus(
      connection.status,
      connection.available_tools.length
    );
    return STATUS_TO_HEALTH[displayStatus] ?? "unknown";
  };

  // Shared status presentation: a coloured dot + label, matching the table design.
  const getStatusIndicator = (status: string) => {
    const presentation = getMcpHealthStatusPresentation(status);
    const label = presentation.labelKey
      ? t(`status.${presentation.labelKey}`)
      : presentation.label;
    return (
      <StatusIndicator tone={presentation.tone} pulse={presentation.pulse}>
        {label}
      </StatusIndicator>
    );
  };

  // Subtitle under the connection name — transport for MCP, host for OpenAPI.
  const rowSubtitle = (item: any): string => {
    if (item._type === "openapi" && item._connection) {
      return hostOf(item._connection.base_url) || "OpenAPI";
    }
    const type = (item._instance?.json_spec?.type as string) || "";
    if (type === "url") return "Remote MCP";
    if (type === "bundle") return "Bundle";
    if (type === "docker") return "Docker";
    return "MCP server";
  };

  // Define table columns for instances
  const instanceColumns = [
    {
      accessor: "name",
      header: t("table.name"),
      render: (value: string, item: any) => {
        const providerIcon =
          item._type === "mcp" && item._instance
            ? getMCPConnectionIconSrc(item._instance, item._serverSpec)
            : undefined;
        return (
          <div className="flex min-w-0 items-center gap-3">
            {item._type === "openapi" && item._connection ? (
              <OpenAPIConnectionMark
                connection={item._connection}
                className="h-7 w-7 shrink-0 rounded-lg text-[9px]"
              />
            ) : (
              <span className="grid h-7 w-7 shrink-0 place-items-center overflow-hidden rounded-lg border border-border bg-white dark:bg-zinc-800">
                {providerIcon ? (
                  <img
                    src={providerIcon}
                    alt=""
                    aria-hidden="true"
                    className="h-[18px] w-[18px] object-contain"
                  />
                ) : (
                  <span className="text-[11px] font-bold text-muted-foreground">
                    {(value?.[0] || "?").toUpperCase()}
                  </span>
                )}
              </span>
            )}
            <div className="min-w-0">
              <div className="truncate text-[13px] font-medium text-foreground">
                {value}
              </div>
              <div className="truncate text-[11px] text-muted-foreground">
                {rowSubtitle(item)}
              </div>
            </div>
          </div>
        );
      },
    },
    {
      accessor: "description",
      header: t("table.description"),
      render: (value: string) => (
        <span className="line-clamp-1 text-[12.5px] text-muted-foreground">
          {cleanDescription(value) || "—"}
        </span>
      ),
    },
    {
      accessor: "endpoint_url",
      header: t("table.endpoint"),
      render: (value: string) => (
        <span className="truncate font-mono text-[11.5px] text-muted-foreground/70">
          {value || "—"}
        </span>
      ),
    },
    {
      accessor: "tools",
      header: "Tools",
      render: (_: unknown, item: any) => {
        const count =
          item._type === "openapi" && item._connection
            ? item._connection.available_tools.length
            : getMCPInstanceToolCount(item._instance || item);
        return count > 0 ? (
          <span className="font-mono text-[12px] text-foreground/70 tabular-nums">
            {count}
          </span>
        ) : (
          <span className="text-[12px] text-muted-foreground/50">—</span>
        );
      },
    },
    {
      accessor: "status",
      header: t("table.status"),
      render: (_: string, item: any) => {
        const healthStatus =
          item._type === "openapi" && item._connection
            ? getOpenAPIHealthStatus(item._connection)
            : getHealthStatus(item._instance || item);
        return getStatusIndicator(healthStatus);
      },
    },
  ];

  const totalItems = mcpInstances.length + openApiConnections.length;

  // Empty state handling
  if (totalItems === 0) {
    return (
      <div className="py-1">
        <EmptyState
          title={hasNoData ? "No connections" : "No matching connections"}
          description={
            hasNoData
              ? "You haven't connected anything yet — add your first connection from the catalog."
              : `No connections match your search query: "${searchQuery}"`
          }
          iconsType="mcp"
        />
        {hasNoData && <CatalogSuggestions type="mcp_servers" />}
      </div>
    );
  }

  // Render table view
  if (viewMode === "table") {
    // Unified rows: MCP instances + OpenAPI connections with a Type column
    const tableRows = [
      ...mcpInstances.map((inst) => ({
        id: inst.id,
        name: inst.name,
        description: inst.description,
        endpoint_url: inst.endpoint_url,
        type: "MCP" as const,
        _type: "mcp" as const,
        _instance: inst,
        _serverSpec: mcpServers.find(
          (server) => server.id === inst.server_spec_id
        ),
        _connection: null,
      })),
      ...openApiConnections.map((conn) => ({
        id: conn.id,
        name: conn.name,
        description: conn.description,
        endpoint_url: conn.base_url,
        type: "OpenAPI" as const,
        _type: "openapi" as const,
        _instance: null,
        _serverSpec: undefined,
        _connection: conn,
      })),
    ];

    const unifiedColumns = [
      {
        accessor: "type",
        header: "Type",
        render: (value: string) => (
          <Badge
            variant="outline"
            className={
              value === "OpenAPI"
                ? "gap-1.5 border-orange-300 text-orange-600"
                : "gap-1.5"
            }
          >
            {value === "OpenAPI" ? (
              <OpenAPIConnectionMark className="h-3.5 w-3.5 rounded-sm text-[6px]" />
            ) : (
              <img src="/mcp.svg" alt="" className="h-3.5 w-3.5" />
            )}
            {value}
          </Badge>
        ),
      },
      ...instanceColumns,
    ];

    return (
      <Table
        data={tableRows}
        columns={unifiedColumns}
        onRowClick={(row) => {
          if (row._type === "openapi") {
            router.push(`/mcp-servers/openapi/${row.id}`);
          } else {
            router.push(`/mcp-servers/${row.id}`);
          }
        }}
      />
    );
  }

  // Render grid view (default)
  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
      {mcpInstances.map((instance) => {
        const serverSpec = mcpServers.find(
          (server) => server.id === instance.server_spec_id
        );
        return (
          <MCPInstanceCard
            key={instance.id}
            instance={instance}
            serverSpec={serverSpec}
          />
        );
      })}
      {openApiConnections.map((connection) => (
        <OpenAPIConnectionCard
          key={`openapi-${connection.id}`}
          connection={connection}
        />
      ))}
    </div>
  );
}
