"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AlertCircle, CheckCircle, Clock, XCircle } from "lucide-react";
import EmptyState from "@/components/EmptyState";
import Table from "@/components/Table/Table";
import { Badge } from "@/components/ui/badge";
import { getMCPHealthStatus } from "@/lib/browser-api";
import { MCPInstanceCard } from "./MCPCard";

interface MCPInstance {
  id: string;
  name: string;
  description?: string | null;
  status: string;
  endpoint_url?: string;
  created_at: string;
  server_spec_id?: string | null;
  json_spec?: any;
}

interface HealthCheck {
  service_name: string;
  slug: string;
  url: string;
  healthy: boolean;
  http_reachable: boolean;
  response_time_ms: number;
  error?: string;
}

interface MyMCPsSectionProps {
  mcpInstances: MCPInstance[];
  viewMode?: string;
  searchQuery?: string;
  hasNoData?: boolean;
}

export function MyMCPsSection({
  mcpInstances,
  viewMode = "grid",
  searchQuery = "",
  hasNoData = false,
}: MyMCPsSectionProps) {
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
    const interval = setInterval(fetchHealthStatus, 60000);
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
  const getHealthStatus = (
    instance: MCPInstance
  ): "healthy" | "unhealthy" | "starting" | "unknown" => {
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
      case "healthy":
      case "running":
        return (
          <Badge variant="success" className="w-fit">
            <CheckCircle className="mr-1 h-3 w-3" />
            Running
          </Badge>
        );
      case "unhealthy":
      case "error":
        return (
          <Badge variant="destructive" className="w-fit">
            <XCircle className="mr-1 h-3 w-3" />
            Error
          </Badge>
        );
      case "starting":
        return (
          <Badge variant="yellow" className="w-fit">
            <Clock className="mr-1 h-3 w-3" />
            Starting
          </Badge>
        );
      default:
        return (
          <Badge variant="yellow" className="w-fit">
            <AlertCircle className="mr-1 h-3 w-3" />
            Setup
          </Badge>
        );
    }
  };

  // Define table columns for instances
  const instanceColumns = [
    {
      accessor: "name",
      header: "Name",
      render: (value: string) => <span className="truncate">{value}</span>,
    },
    {
      accessor: "description",
      header: "Description",
      render: (value: string) => (
        <span className="truncate text-sm text-gray-500">{value || "-"}</span>
      ),
    },
    {
      accessor: "endpoint_url",
      header: "Endpoint",
      render: (value: string) => (
        <span className="truncate font-mono text-xs text-gray-400">
          {value || "-"}
        </span>
      ),
    },
    {
      accessor: "status",
      header: "Status",
      render: (_: string, item: MCPInstance) => {
        const healthStatus = getHealthStatus(item);
        return getStatusBadge(healthStatus);
      },
    },
  ];

  // Empty state handling
  if (mcpInstances.length === 0) {
    return (
      <div className="py-1">
        <EmptyState
          title={hasNoData ? "No MCP instances" : "No matching instances"}
          description={
            hasNoData
              ? "No MCP server instances are configured yet"
              : `No instances match your search query: "${searchQuery}"`
          }
          iconsType="mcp"
        />
      </div>
    );
  }

  // Render table view
  if (viewMode === "table") {
    return (
      <Table
        data={mcpInstances}
        columns={instanceColumns}
        onRowClick={(instance) => {
          router.push(`/mcp-servers/${instance.id}`);
        }}
      />
    );
  }

  // Render grid view (default)
  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
      {mcpInstances.map((instance) => {
        const healthStatus = getHealthStatus(instance);
        return (
          <MCPInstanceCard
            key={instance.id}
            instance={instance}
            healthStatus={healthStatus}
          />
        );
      })}
    </div>
  );
}
