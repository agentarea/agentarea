"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { AlertCircle, CheckCircle, Clock, XCircle } from "lucide-react";
import EmptyState from "@/components/EmptyState";
import Table from "@/components/Table/Table";
import { Badge } from "@/components/ui/badge";
import { getMCPHealthStatusAction as getMCPHealthStatus } from "@/lib/server-actions";
import { MCPInstanceCard, OpenAPIConnectionCard } from "./MCPCard";
import { MCPInstance, MCPServer, OpenAPIConnection, HealthCheck, HealthStatus } from "../types";
import { MCP_CONSTANTS } from "../utils";

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

  // Get health status for instance
  const getHealthStatus = (instance: MCPInstance): HealthStatus => {
    const healthCheck = getHealthCheck(instance.name);

    if (healthLoading) return "unknown";
    if (!healthCheck) return "unknown";
    if (healthCheck.healthy && healthCheck.http_reachable) return "healthy";
    if (!healthCheck.http_reachable) return "starting";
    return "unhealthy";
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
      render: (value: string) => <span className="truncate">{value}</span>,
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
      accessor: "status",
      header: t("table.status"),
      render: (_: string, item: MCPInstance) => {
        const healthStatus = getHealthStatus(item);
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
      })),
      ...openApiConnections.map((conn) => ({
        id: conn.id,
        name: conn.name,
        description: conn.description,
        endpoint_url: conn.base_url,
        type: "OpenAPI" as const,
        _type: "openapi" as const,
        _instance: null as MCPInstance | null,
      })),
    ];

    const unifiedColumns = [
      {
        accessor: "type",
        header: "Type",
        render: (value: string) => (
          <Badge variant="outline" className={
            value === "OpenAPI" ? "border-orange-300 text-orange-600" : ""
          }>
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
        const serverSpec = mcpServers.find((server) => server.id === instance.server_spec_id);
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
