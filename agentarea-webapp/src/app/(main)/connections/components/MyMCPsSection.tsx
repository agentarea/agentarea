"use client";

import { useTranslations } from "next-intl";
import Image from "next/image";
import { useRouter } from "next/navigation";
import CatalogSuggestions from "@/components/CatalogSuggestions";
import EmptyState from "@/components/EmptyState";
import Table from "@/components/Table/Table";
import { Badge } from "@/components/ui/badge";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { CARD_GRID_DENSE } from "@/lib/collectionGrids";
import {
  getMcpHealthStatusPresentation,
  getMcpVerificationStatusPresentation,
  getOpenApiConnectionDisplayStatus,
  type StatusPresentation,
} from "@/lib/status";
import { MCPInstance, MCPServer, OpenAPIConnection } from "../types";
import {
  getEffectiveMCPVerificationStatus,
  getMCPConnectionIconSrc,
  getMCPInstanceToolCount,
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

// An OpenAPI connection's own status, in the vocabulary the shared status
// presenter speaks. Unlike MCP workloads there is nothing to start on demand
// here — the connection either reaches its upstream spec or it does not.
const OPENAPI_STATUS_TO_HEALTH: Record<string, string> = {
  connected: "connected",
  succeeded: "connected",
  running: "healthy",
  failed: "unhealthy",
  stopped: "unknown",
  pending: "starting",
  starting: "starting",
};

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

  // Shared status presentation: a coloured dot + label, matching the table design.
  const getStatusIndicator = (presentation: StatusPresentation) => {
    const label = presentation.labelKey
      ? t(`status.${presentation.labelKey}`)
      : presentation.label;
    return (
      <StatusIndicator tone={presentation.tone} pulse={presentation.pulse}>
        {label}
      </StatusIndicator>
    );
  };

  type TableRow = {
    id: string;
    name: string;
    description: string | null | undefined;
    endpoint_url: string | null | undefined;
    type: "MCP" | "OpenAPI";
    _type: "mcp" | "openapi";
    _instance: MCPInstance | null;
    _serverSpec: MCPServer | undefined;
    _connection: OpenAPIConnection | null;
  };

  // Subtitle under the connection name — transport for MCP, host for OpenAPI.
  const rowSubtitle = (item: TableRow): string => {
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
      render: (value: string, item: TableRow) => {
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
                  <Image
                    src={providerIcon}
                    alt=""
                    aria-hidden="true"
                    width={18}
                    height={18}
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
      render: (_: unknown, item: TableRow) => {
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
      // Whether the connection works — the same verdict the cards show. Not
      // whether a container is warm: workloads start on demand and are reaped
      // when idle, so liveness is the data plane's business, not a column here.
      render: (_: string, item: TableRow) => {
        if (item._type === "openapi" && item._connection) {
          const displayStatus = getOpenApiConnectionDisplayStatus(
            item._connection.status,
            item._connection.available_tools.length
          );
          return getStatusIndicator(
            getMcpHealthStatusPresentation(
              OPENAPI_STATUS_TO_HEALTH[displayStatus] ?? "unknown"
            )
          );
        }
        if (!item._instance) return null;
        return getStatusIndicator(
          getMcpVerificationStatusPresentation(
            getEffectiveMCPVerificationStatus(item._instance)
          )
        );
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
              <Image
                src="/mcp.svg"
                alt=""
                width={14}
                height={14}
                className="h-3.5 w-3.5"
              />
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
            router.push(`/connections/openapi/${row.id}`);
          } else {
            router.push(`/connections/${row.id}`);
          }
        }}
      />
    );
  }

  // Render grid view (default)
  return (
    <div className={CARD_GRID_DENSE}>
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
