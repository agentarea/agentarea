"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { formatDistanceToNow } from "date-fns";
import { Server } from "lucide-react";
import CatalogSuggestions from "@/components/CatalogSuggestions";
import EmptyState from "@/components/EmptyState";
import Table from "@/components/Table/Table";
import { Badge } from "@/components/ui/badge";
import { EntityAvatar } from "@/components/ui/entity-avatar";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { deterministicHue } from "@/lib/avatar-hue";
import { CARD_GRID_DENSE } from "@/lib/collectionGrids";
import { getMCPConnectionIconSrc } from "@/lib/entity-identity";
import { getOpenApiConnectionDisplayStatus } from "@/lib/status";
import { cn } from "@/lib/utils";
import { LIST_FILTERS } from "../list-sections";
import {
  getMcpConnectionState,
  getOpenApiConnectionState,
  type ConnectionState,
} from "../state";
import { MCPInstance, MCPServer, OpenAPIConnection } from "../types";
import type { ConnectionUsage } from "../usage";
import { useConnectionListFilter } from "../useConnectionListFilter";
import { getMCPInstanceToolCount } from "../utils";
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
  /** Per-connection usage, keyed by MCP instance id. */
  usage?: Record<string, ConnectionUsage>;
  viewMode?: string;
  searchQuery?: string;
  hasNoData?: boolean;
}

export function MyMCPsSection({
  mcpInstances,
  mcpServers,
  openApiConnections = [],
  usage = {},
  viewMode = "grid",
  searchQuery = "",
  hasNoData = false,
}: MyMCPsSectionProps) {
  const t = useTranslations("MCPServersPage");
  const router = useRouter();

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
    _state: ConnectionState;
    _usage: ConnectionUsage | undefined;
  };

  // One row per connection, shared by both views: the verdict and usage decide
  // filtering and grouping, so they are computed once rather than per cell.
  const rows = useMemo<TableRow[]>(
    () => [
      ...mcpInstances.map((inst) => {
        const instanceUsage = usage[inst.id];
        return {
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
          _state: getMcpConnectionState({
            verification: inst.verification,
            last_dispatch: inst.last_dispatch,
            toolCount: getMCPInstanceToolCount(inst),
          }),
          _usage: instanceUsage,
        };
      }),
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
        _state: getOpenApiConnectionState(
          getOpenApiConnectionDisplayStatus(
            conn.status,
            conn.available_tools.length
          ),
          conn.available_tools.length
        ),
        _usage: undefined,
      })),
    ],
    [mcpInstances, mcpServers, openApiConnections, usage]
  );

  const {
    filter,
    setFilter,
    counts,
    visibleRows,
    sections,
    showSectionHeadings,
  } = useConnectionListFilter(rows);

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
              <EntityAvatar
                size={28}
                rounded={8}
                hue={deterministicHue(item.id || value || "mcp")}
                iconScale={providerIcon ? 0.68 : 0.5}
                icon={
                  providerIcon ? (
                    <Image
                      src={providerIcon}
                      alt=""
                      aria-hidden="true"
                      width={18}
                      height={18}
                      className="h-full w-full object-contain"
                    />
                  ) : (
                    <Server strokeWidth={1.85} />
                  )
                }
                aria-hidden
              />
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
      accessor: "usedBy",
      header: t("table.usedBy"),
      // Who actually holds this connection, and how much of it. A bare tool
      // count says nothing: 400 available with 12 granted is a healthy
      // connection, 400 available with all granted is a blast radius.
      render: (_: unknown, item: TableRow) => {
        const total =
          item._type === "openapi" && item._connection
            ? item._connection.available_tools.length
            : getMCPInstanceToolCount(item._instance || item);
        const connectionUsage =
          item._type === "mcp" ? usage[item.id] : undefined;

        if (!connectionUsage) {
          return (
            <span className="font-mono text-[12px] text-muted-foreground/60 tabular-nums">
              {total > 0 ? t("table.toolsTotal", { total }) : "—"}
            </span>
          );
        }

        const granted =
          connectionUsage.grantedTools === null
            ? t("table.allTools")
            : `${connectionUsage.grantedTools} / ${total}`;

        return (
          <div className="flex flex-col gap-0.5">
            <span
              className={
                connectionUsage.agents === 0
                  ? "text-[12px] text-muted-foreground/60"
                  : "text-[12px] text-foreground/80"
              }
            >
              {connectionUsage.agents === 0
                ? t("table.unused")
                : t("table.agentCount", { count: connectionUsage.agents })}
            </span>
            <span className="font-mono text-[11px] text-muted-foreground tabular-nums">
              {t("table.toolsGranted", { granted })}
            </span>
          </div>
        );
      },
    },
    {
      accessor: "state",
      header: t("table.state"),
      // One verdict from the two facts we record: the setup-time verification
      // probe and the outcome of the last real tool call. Never liveness —
      // workloads start on demand and are reaped when idle, so "connected" is
      // not a state this product has.
      render: (_: unknown, item: TableRow) => {
        const connectionState =
          item._type === "openapi" && item._connection
            ? getOpenApiConnectionState(
                getOpenApiConnectionDisplayStatus(
                  item._connection.status,
                  item._connection.available_tools.length
                ),
                item._connection.available_tools.length
              )
            : item._instance
              ? getMcpConnectionState({
                  verification: item._instance.verification,
                  last_dispatch: item._instance.last_dispatch,
                  toolCount: getMCPInstanceToolCount(item._instance),
                })
              : null;
        if (!connectionState) return null;

        // The timestamp means different things per verdict — call time for
        // working/failing, probe time for broken — so a state that has never
        // been called says so instead of dating its setup.
        const secondary =
          connectionState.key === "ready"
            ? t("state.neverCalled")
            : connectionState.at
              ? formatDistanceToNow(new Date(connectionState.at), {
                  addSuffix: true,
                })
              : null;

        return (
          <div className="flex flex-col gap-0.5">
            <StatusIndicator
              tone={connectionState.tone}
              pulse={connectionState.pulse}
            >
              {t(`state.${connectionState.key}`)}
            </StatusIndicator>
            {secondary && (
              <span className="pl-3.5 text-[11px] text-muted-foreground">
                {secondary}
              </span>
            )}
          </div>
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
          title={hasNoData ? "No connections yet" : "No matching connections"}
          description={
            hasNoData
              ? "A connection is an outside system — an MCP server or an OpenAPI service — whose tools your agents are allowed to call."
              : `No connections match your search query: "${searchQuery}"`
          }
          hints={
            hasNoData
              ? [
                  { text: "Add an MCP server", href: "/connections/add" },
                  {
                    text: "Connect an OpenAPI service from its spec",
                    href: "/connections/add-openapi",
                  },
                  {
                    text: "Install a ready-made connection from the catalog",
                    href: "/explore?type=connections",
                  },
                ]
              : undefined
          }
          iconsType="mcp"
          action={
            hasNoData
              ? { label: "Add connection", href: "/connections/add" }
              : { label: "Clear search", href: "/connections" }
          }
        />
        {hasNoData && <CatalogSuggestions type="connections" />}
      </div>
    );
  }

  const filters = (
    <div className="mb-3 flex flex-wrap items-center gap-1">
      {LIST_FILTERS.map((key) => (
        <button
          key={key}
          type="button"
          onClick={() => setFilter(key)}
          disabled={key !== "all" && counts[key] === 0}
          className={cn(
            "rounded-md border px-2 py-1 text-[11px] transition-colors",
            filter === key
              ? "border-primary/40 bg-primary/10 text-foreground"
              : "border-border text-muted-foreground hover:bg-muted/50",
            key !== "all" &&
              counts[key] === 0 &&
              "opacity-40 hover:bg-transparent"
          )}
        >
          {t(`listFilters.${key}`)}
          <span className="ml-1 tabular-nums">{counts[key]}</span>
        </button>
      ))}
    </div>
  );

  const unifiedColumns = [
    {
      accessor: "type",
      header: t("filters.type"),
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

  const openRow = (row: TableRow) => {
    router.push(
      row._type === "openapi"
        ? `/connections/openapi/${row.id}`
        : `/connections/${row.id}`
    );
  };

  if (visibleRows.length === 0) {
    return (
      <div>
        {filters}
        <EmptyState
          title={t(`listFilters.empty.${filter}`)}
          description={t("listFilters.emptyDescription")}
          iconsType="mcp"
          action={{
            label: t("listFilters.all"),
            onClick: () => setFilter("all"),
          }}
        />
      </div>
    );
  }

  return (
    <div>
      {filters}
      <div className="space-y-5">
        {sections.map((section, index) => (
          <div key={section.key}>
            {showSectionHeadings && (
              <h5 className="mb-2 text-[11px] uppercase tracking-wide text-muted-foreground/80">
                {t(`sections.${section.key}`)} ({section.rows.length})
              </h5>
            )}
            {viewMode === "table" ? (
              <Table
                data={section.rows}
                columns={unifiedColumns}
                onRowClick={openRow}
                hideHeader={index > 0}
              />
            ) : (
              <div className={CARD_GRID_DENSE}>
                {section.rows.map((row) =>
                  row._type === "mcp" && row._instance ? (
                    <MCPInstanceCard
                      key={row.id}
                      instance={row._instance}
                      serverSpec={row._serverSpec}
                      usage={row._usage}
                    />
                  ) : row._connection ? (
                    <OpenAPIConnectionCard
                      key={`openapi-${row.id}`}
                      connection={row._connection}
                    />
                  ) : null
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
