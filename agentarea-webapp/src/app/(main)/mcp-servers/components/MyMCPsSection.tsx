"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { AlertCircle, CheckCircle, Clock, XCircle } from "lucide-react";
import EmptyState from "@/components/EmptyState";
import Table from "@/components/Table/Table";
import { Badge } from "@/components/ui/badge";
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
    if (connection.status === "failed") return "unhealthy";
    if (connection.status === "pending" || connection.status === "starting") {
      return "starting";
    }
    if (
      connection.status === "connected" ||
      connection.status === "running" ||
      connection.status === "succeeded" ||
      connection.available_tools.length > 0
    ) {
      return "connected";
    }
    return STATUS_TO_HEALTH[connection.status] ?? "unknown";
  };

  // Get status badge component
  const getStatusBadge = (status: string) => {
    switch (status) {
      case "connected":
        return (
          <Badge variant="teal" className="w-fit">
            <CheckCircle className="mr-1 h-3 w-3" />
            {t("status.connected")}
          </Badge>
        );
      case "healthy":
      case "running":
        return (
          <Badge variant="success" className="w-fit">
            <CheckCircle className="mr-1 h-3 w-3" />
            {t("status.running")}
          </Badge>
        );
      case "unhealthy":
      case "error":
        return (
          <Badge variant="destructive" className="w-fit">
            <XCircle className="mr-1 h-3 w-3" />
            {t("status.error")}
          </Badge>
        );
      case "starting":
        return (
          <Badge variant="yellow" className="w-fit">
            <Clock className="mr-1 h-3 w-3" />
            {t("status.starting")}
          </Badge>
        );
      default:
        return (
          <Badge variant="yellow" className="w-fit">
            <AlertCircle className="mr-1 h-3 w-3" />
            {t("status.setup")}
          </Badge>
        );
    }
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
          <span className="flex min-w-0 items-center gap-2">
            {item._type === "openapi" && item._connection ? (
              <OpenAPIConnectionMark
                connection={item._connection}
                className="h-5 w-5 shrink-0 rounded text-[7px]"
              />
            ) : providerIcon ? (
              <img
                src={providerIcon}
                alt=""
                aria-hidden="true"
                className="h-5 w-5 shrink-0 rounded object-contain"
              />
            ) : null}
            <span className="truncate">{value}</span>
          </span>
        );
      },
    },
    {
      accessor: "description",
      header: t("table.description"),
      render: (value: string) => (
        <span className="truncate text-sm text-gray-500">{value || "-"}</span>
      ),
    },
    {
      accessor: "endpoint_url",
      header: t("table.endpoint"),
      render: (value: string) => (
        <span className="truncate font-mono text-xs text-gray-400">
          {value || "-"}
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
          <span className="text-sm text-muted-foreground">{count}</span>
        ) : (
          <span className="text-sm text-gray-400">-</span>
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
        return getStatusBadge(healthStatus);
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
              ? "No MCP servers or OpenAPI connections configured yet"
              : `No connections match your search query: "${searchQuery}"`
          }
          iconsType="mcp"
        />
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
