"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { AlertCircle, CheckCircle, Clock, XCircle } from "lucide-react";
import CollectionView, {
  type CollectionItem,
} from "@/components/CollectionView";
import EmptyState from "@/components/EmptyState";
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
import { OpenAPIConnectionMark } from "./MCPCard";

interface MyMCPsSectionProps {
  mcpInstances: MCPInstance[];
  mcpServers: MCPServer[];
  openApiConnections?: OpenAPIConnection[];
  viewMode?: string;
  searchQuery?: string;
  hasNoData?: boolean;
}

const MCP_COLOR = "#5e6ad2";
const OPENAPI_COLOR = "#d97706";

export function MyMCPsSection({
  mcpInstances,
  mcpServers,
  openApiConnections = [],
  viewMode = "grid",
  searchQuery = "",
  hasNoData = false,
}: MyMCPsSectionProps) {
  const t = useTranslations("MCPServersPage");
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

  const items: CollectionItem[] = [
    ...mcpInstances.map((instance): CollectionItem => {
      const serverSpec = mcpServers.find(
        (server) => server.id === instance.server_spec_id
      );
      const providerIcon = getMCPConnectionIconSrc(instance, serverSpec);
      const count = getMCPInstanceToolCount(instance);
      const health = getHealthStatus(instance);
      return {
        id: instance.id,
        color: MCP_COLOR,
        icon: (
          <img
            src={providerIcon || "/mcp.svg"}
            alt=""
            aria-hidden="true"
            className="h-4 w-4 rounded object-contain"
          />
        ),
        title: instance.name,
        description: instance.description,
        href: `/mcp-servers/${instance.id}`,
        badges: [{ label: "MCP", color: MCP_COLOR }],
        meta: (
          <span className="flex items-center gap-2">
            {count > 0 && <span>{count}</span>}
            {getStatusBadge(health)}
          </span>
        ),
      };
    }),
    ...openApiConnections.map((connection): CollectionItem => {
      const health = getOpenAPIHealthStatus(connection);
      const count = connection.available_tools.length;
      return {
        id: connection.id,
        color: OPENAPI_COLOR,
        icon: (
          <OpenAPIConnectionMark
            connection={connection}
            className="h-4 w-4 rounded text-[7px]"
          />
        ),
        title: connection.name,
        description: connection.description,
        href: `/mcp-servers/openapi/${connection.id}`,
        badges: [{ label: "OpenAPI", color: OPENAPI_COLOR }],
        meta: (
          <span className="flex items-center gap-2">
            {count > 0 && <span>{count}</span>}
            {getStatusBadge(health)}
          </span>
        ),
      };
    }),
  ];

  return (
    <CollectionView
      view={viewMode === "table" ? "list" : "grid"}
      items={items}
      bleed
    />
  );
}
