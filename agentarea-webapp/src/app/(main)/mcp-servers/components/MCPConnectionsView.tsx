"use client";

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  Activity,
  ArrowDownAZ,
  Boxes,
  Check,
  ChevronDown,
  LayoutGrid,
  Rows3,
  Tag,
} from "lucide-react";
import CollectionView, {
  CollectionToolbar,
  type CollectionGroup,
  type CollectionItem,
} from "@/components/CollectionView";
import EmptyState from "@/components/EmptyState";
import { cn } from "@/lib/utils";
import { getMCPHealthStatusAction as getMCPHealthStatus } from "@/lib/server-actions";
import { setCookie } from "@/utils/cookies";
import {
  HealthCheck,
  HealthStatus,
  MCPInstance,
  MCPServer,
  OpenAPIConnection,
} from "../types";
import {
  getConnectionType,
  getEffectiveMCPVerificationStatus,
  getMCPConnectionIconSrc,
  getMCPInstanceToolCount,
  MCP_CONSTANTS,
} from "../utils";
import { OpenAPIConnectionMark } from "./MCPCard";

type ViewKey = "list" | "grid";
type TabKey = "all" | "mcp" | "openapi";
type GroupKey = "none" | "status" | "type";
type OrderKey = "name" | "status";

export interface MCPConnectionsInitialState {
  view: ViewKey;
  tab: TabKey;
  group: GroupKey;
  order: OrderKey;
  search: string;
}

interface MCPConnectionsViewProps {
  mcpInstances: MCPInstance[];
  mcpServers: MCPServer[];
  openApiConnections: OpenAPIConnection[];
  initial: MCPConnectionsInitialState;
}

/* brand / protocol colours (Connections design) */
const MCP_COLOR = "#5e6ad2";
const API_COLOR = "#cf6a2a";

/* status buckets — dot + label colour, used for the chip, grouping + ordering */
const STATUS_BUCKETS: {
  key: string;
  label: string;
  color: string;
  match: HealthStatus[];
}[] = [
  { key: "connected", label: "Connected", color: "#1f9a6d", match: ["connected", "healthy"] },
  { key: "starting", label: "Starting", color: "#c98a12", match: ["starting"] },
  { key: "error", label: "Error", color: "#d6453d", match: ["unhealthy"] },
  { key: "setup", label: "Setup", color: "#c98a12", match: ["unknown"] },
];

function statusMeta(health: HealthStatus) {
  return (
    STATUS_BUCKETS.find((b) => b.match.includes(health)) ??
    STATUS_BUCKETS[STATUS_BUCKETS.length - 1]
  );
}

/* ── small presentational pieces (match the prototype) ─────────────────── */

function mcpGlyph(color: string, size = 12) {
  return (
    <span
      aria-hidden
      style={{
        width: size,
        height: size,
        backgroundColor: color,
        maskImage: "url(/mcp.svg)",
        WebkitMaskImage: "url(/mcp.svg)",
        maskSize: "contain",
        WebkitMaskSize: "contain",
        maskRepeat: "no-repeat",
        WebkitMaskRepeat: "no-repeat",
        maskPosition: "center",
        WebkitMaskPosition: "center",
      }}
    />
  );
}

function TypePill({ kind }: { kind: "mcp" | "api" }) {
  const color = kind === "mcp" ? MCP_COLOR : API_COLOR;
  return (
    <span
      className="inline-flex h-[20px] shrink-0 items-center gap-1 rounded-md border px-[7px] text-[11px] font-medium"
      style={{
        color,
        background: `color-mix(in srgb, ${color} 8%, var(--tile-base))`,
        borderColor: `color-mix(in srgb, ${color} 32%, var(--tile-base))`,
      }}
    >
      {kind === "mcp" && mcpGlyph(color, 12)}
      {kind === "mcp" ? "MCP" : "OpenAPI"}
    </span>
  );
}

function StatusDot({ health }: { health: HealthStatus }) {
  const s = statusMeta(health);
  return (
    <span
      className="inline-flex items-center gap-1.5 whitespace-nowrap text-[11.5px] font-medium"
      style={{ color: s.color }}
    >
      <span className="h-[7px] w-[7px] rounded-full" style={{ background: s.color }} />
      {s.label}
    </span>
  );
}

function Dash() {
  return <span className="text-muted-foreground/50">–</span>;
}

/** Absolute date dd.mm.yyyy (the spec catalog uses an updated-on date). */
function fmtDate(iso?: string | null) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getDate())}.${p(d.getMonth() + 1)}.${d.getFullYear()}`;
}

/** Orange "Custom" pill shown on catalog spec rows. */
function CustomPill() {
  return (
    <span
      className="inline-flex h-[20px] items-center rounded-md border px-[7px] text-[11px] font-medium"
      style={{
        color: API_COLOR,
        background: `color-mix(in srgb, ${API_COLOR} 7%, var(--tile-base))`,
        borderColor: `color-mix(in srgb, ${API_COLOR} 36%, var(--tile-base))`,
      }}
    >
      Custom
    </span>
  );
}

/** Neutral "Tools" pill (grid glyph + label). */
function ToolsPill() {
  return (
    <span className="inline-flex h-[20px] items-center gap-1 rounded-md border border-border bg-background px-[7px] text-[11px] font-medium text-foreground/70">
      <LayoutGrid className="h-3 w-3" strokeWidth={1.8} />
      Tools
    </span>
  );
}

/** Monospace version chip (muted background). */
function VersionChip({ version }: { version: string }) {
  return (
    <span className="inline-flex h-[20px] items-center rounded-md bg-muted px-[7px] font-mono text-[11px] font-medium text-muted-foreground">
      v{version}
    </span>
  );
}

function SectionHeaderInner({
  icon,
  name,
  count,
  sub,
}: {
  icon: ReactNode;
  name: string;
  count: number;
  sub: string;
}) {
  return (
    <>
      <span className="grid h-[18px] w-[18px] shrink-0 place-items-center rounded-[5px] bg-primary/10 text-primary">
        {icon}
      </span>
      <span className="text-[12.5px] font-semibold text-foreground">{name}</span>
      <span className="rounded-full bg-muted px-[7px] text-[11.5px] leading-[17px] text-muted-foreground">
        {count}
      </span>
      <span className="truncate text-[11.5px] font-normal text-muted-foreground/70">
        {sub}
      </span>
    </>
  );
}

function SectionHeader({
  icon,
  name,
  count,
  sub,
  variant,
  collapsed,
  onToggle,
}: {
  icon: ReactNode;
  name: string;
  count: number;
  sub: string;
  variant: ViewKey;
  collapsed: boolean;
  onToggle: () => void;
}) {
  // Grid view: plain header — no hatch background, no collapse chevron.
  if (variant === "grid") {
    return (
      <div className="flex items-center gap-2 px-4 pb-2.5 pt-5">
        <SectionHeaderInner icon={icon} name={name} count={count} sub={sub} />
      </div>
    );
  }
  // List view: hatched, sticky, collapsible bar.
  return (
    <button
      type="button"
      onClick={onToggle}
      className="collection-hatch sticky top-0 z-[3] flex h-9 w-full items-center gap-2 border-b border-t border-zinc-100 px-4 first:border-t-0 dark:border-zinc-800/70"
    >
      <ChevronDown
        className={cn(
          "h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform",
          collapsed && "-rotate-90"
        )}
      />
      <SectionHeaderInner icon={icon} name={name} count={count} sub={sub} />
    </button>
  );
}

/* ── view ──────────────────────────────────────────────────────────────── */

export default function MCPConnectionsView({
  mcpInstances,
  mcpServers,
  openApiConnections,
  initial,
}: MCPConnectionsViewProps) {
  const t = useTranslations("MCPServersPage");
  const tCommon = useTranslations("Common");
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const [view, setView] = useState<ViewKey>(initial.view);
  const [tab, setTab] = useState<TabKey>(initial.tab);
  const [group, setGroup] = useState<GroupKey>(initial.group);
  const [order, setOrder] = useState<OrderKey>(initial.order);
  const [search, setSearch] = useState(initial.search);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  // ── health polling (drives connection status) ──
  const [healthChecks, setHealthChecks] = useState<HealthCheck[]>([]);
  const [healthLoading, setHealthLoading] = useState(true);

  useEffect(() => {
    let active = true;
    const fetchHealthStatus = async () => {
      try {
        const data = await getMCPHealthStatus();
        if (active) setHealthChecks(data.health_checks);
      } catch (error) {
        console.error("Failed to fetch health status:", error);
      } finally {
        if (active) setHealthLoading(false);
      }
    };
    fetchHealthStatus();
    const interval = setInterval(
      fetchHealthStatus,
      MCP_CONSTANTS.HEALTH_CHECK_INTERVAL_MS
    );
    return () => {
      active = false;
      clearInterval(interval);
    };
  }, []);

  const getHealthCheck = useCallback(
    (instanceName: string): HealthCheck | undefined => {
      let healthCheck = healthChecks.find((c) => c.service_name === instanceName);
      if (!healthCheck) {
        const normalized = instanceName
          .toLowerCase()
          .replace(/\s+/g, "-")
          .replace(/[^a-z0-9-]/g, "");
        healthCheck = healthChecks.find(
          (c) =>
            c.service_name === normalized ||
            c.service_name.includes(normalized) ||
            normalized.includes(c.service_name)
        );
      }
      return healthCheck;
    },
    [healthChecks]
  );

  const getInstanceHealth = useCallback(
    (instance: MCPInstance): HealthStatus => {
      const instanceType = (instance.json_spec?.type as string) || "docker";
      const vStatus = getEffectiveMCPVerificationStatus(instance);
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
    },
    [getHealthCheck, healthLoading]
  );

  const getOpenAPIHealth = useCallback((connection: OpenAPIConnection): HealthStatus => {
    if (connection.status === "failed") return "unhealthy";
    if (connection.status === "pending" || connection.status === "starting")
      return "starting";
    if (
      connection.status === "connected" ||
      connection.status === "running" ||
      connection.status === "succeeded" ||
      connection.available_tools.length > 0
    )
      return "connected";
    return "unknown";
  }, []);

  // ── URL sync ──
  const syncUrl = useCallback(
    (next: Partial<MCPConnectionsInitialState>) => {
      const merged = { view, tab, group, order, search, ...next };
      const params = new URLSearchParams(searchParams.toString());
      const set = (key: string, value: string, empty: string) => {
        if (value && value !== empty) params.set(key, value);
        else params.delete(key);
      };
      set("view", merged.view, "grid");
      set("protocol", merged.tab, "all");
      set("group", merged.group, "none");
      set("order", merged.order, "name");
      set("search", merged.search, "");
      const query = params.toString();
      router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
    },
    [view, tab, group, order, search, searchParams, router, pathname]
  );

  // ── connection entries ──
  type ConnEntry = {
    item: CollectionItem;
    kind: "mcp" | "api";
    health: HealthStatus;
    name: string;
  };

  const connMeta = useCallback(
    (kind: "mcp" | "api", endpoint: string | null, tools: number, health: HealthStatus) => (
      <span
        className="grid items-center gap-2.5"
        style={{ gridTemplateColumns: "76px 150px 60px 92px" }}
      >
        <TypePill kind={kind} />
        <span className="truncate font-mono text-[11.5px] text-muted-foreground/70">
          {endpoint || <Dash />}
        </span>
        <span className="text-[11.5px] text-muted-foreground">
          {tools > 0 ? `${tools} tools` : <Dash />}
        </span>
        <StatusDot health={health} />
      </span>
    ),
    []
  );

  const connCardFooter = useCallback(
    (kind: "mcp" | "api", tools: number, health: HealthStatus) => (
      <div className="flex items-center gap-2.5 pr-6">
        <TypePill kind={kind} />
        {kind === "api" ? (
          <span className="text-[11.5px] text-muted-foreground">
            {tools > 0 ? `${tools} tools` : <Dash />}
          </span>
        ) : (
          <StatusDot health={health} />
        )}
      </div>
    ),
    []
  );

  const connEntries = useMemo<ConnEntry[]>(() => {
    const mcp = mcpInstances.map((instance): ConnEntry => {
      const serverSpec = mcpServers.find((s) => s.id === instance.server_spec_id);
      const providerIcon = getMCPConnectionIconSrc(instance, serverSpec);
      const tools = getMCPInstanceToolCount(instance);
      const health = getInstanceHealth(instance);
      const endpoint = (instance.endpoint_url as string | undefined) || null;
      return {
        kind: "mcp",
        health,
        name: instance.name,
        item: {
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
          hideDescription: true,
          meta: connMeta("mcp", endpoint, tools, health),
          cardFooter: connCardFooter("mcp", tools, health),
        },
      };
    });
    const api = openApiConnections.map((connection): ConnEntry => {
      const tools = connection.available_tools.length;
      const health = getOpenAPIHealth(connection);
      return {
        kind: "api",
        health,
        name: connection.name,
        item: {
          id: connection.id,
          color: API_COLOR,
          icon: (
            <OpenAPIConnectionMark
              connection={connection}
              className="h-4 w-4 rounded text-[7px]"
            />
          ),
          title: connection.name,
          description: connection.description,
          href: `/mcp-servers/openapi/${connection.id}`,
          hideDescription: true,
          meta: connMeta("api", connection.base_url, tools, health),
          cardFooter: connCardFooter("api", tools, health),
        },
      };
    });
    return [...mcp, ...api];
  }, [
    mcpInstances,
    mcpServers,
    openApiConnections,
    getInstanceHealth,
    getOpenAPIHealth,
    connMeta,
    connCardFooter,
  ]);

  // ── spec items (Browse MCP specifications) ──
  const specItems = useMemo<CollectionItem[]>(
    () =>
      mcpServers.map((server) => {
        const iconSrc = (server as { json_spec?: { icons?: { src?: string }[] } })
          .json_spec?.icons?.[0]?.src;
        const title =
          (server as { json_spec?: { title?: string } }).json_spec?.title ||
          server.name;
        const isRemote = getConnectionType(server) === "url";
        const transportColor = isRemote ? MCP_COLOR : "#27a08c";
        return {
          id: server.id,
          color: MCP_COLOR,
          icon: (
            <img
              src={iconSrc || "/mcp.svg"}
              alt=""
              aria-hidden="true"
              className="h-4 w-4 rounded object-contain"
            />
          ),
          title,
          description: server.description,
          href: `/mcp-servers/create/${server.id}`,
          compactDescription: true,
          // fixed title + badge columns so description / badges line up vertically
          titleClassName: "w-[200px] shrink-0",
          afterTitle: (
            <span className="flex w-[132px] items-center gap-1.5">
              {!server.is_public && <CustomPill />}
              <ToolsPill />
            </span>
          ),
          meta: (
            <span
              className="grid items-center gap-2.5 text-[11.5px]"
              style={{ gridTemplateColumns: "56px 84px" }}
            >
              {server.version ? <VersionChip version={server.version} /> : <span />}
              <span className="whitespace-nowrap text-muted-foreground/70">
                {fmtDate(server.updated_at)}
              </span>
            </span>
          ),
          cardFooter: (
            <div className="flex items-center gap-2.5 pr-6 text-[11.5px]">
              {server.version && <VersionChip version={server.version} />}
              <span
                className="inline-flex items-center gap-1.5 font-medium"
                style={{ color: transportColor }}
              >
                <span
                  className="h-[7px] w-[7px] rounded-full"
                  style={{ backgroundColor: transportColor }}
                />
                {isRemote ? "Remote" : "Local"}
              </span>
            </div>
          ),
        };
      }),
    [mcpServers]
  );

  // ── filtering ──
  const q = search.trim().toLowerCase();
  const matchesSearch = useCallback(
    (item: CollectionItem) =>
      !q || `${item.title} ${item.description ?? ""}`.toLowerCase().includes(q),
    [q]
  );

  const visibleConns = useMemo(
    () =>
      connEntries.filter((e) => {
        if (tab === "mcp" && e.kind !== "mcp") return false;
        if (tab === "openapi" && e.kind !== "api") return false;
        return matchesSearch(e.item);
      }),
    [connEntries, tab, matchesSearch]
  );

  const visibleSpecs = useMemo(
    () => (tab === "openapi" ? [] : specItems.filter(matchesSearch)),
    [specItems, tab, matchesSearch]
  );

  const sortConns = useCallback(
    (arr: ConnEntry[]) => {
      const out = [...arr];
      if (order === "status") {
        const rank = (e: ConnEntry) =>
          STATUS_BUCKETS.findIndex((b) => b.match.includes(e.health));
        out.sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));
      } else {
        out.sort((a, b) => a.name.localeCompare(b.name));
      }
      return out;
    },
    [order]
  );

  // ── "My connections" body: groups (list + grouping) or flat items ──
  const mineGroups = useMemo<CollectionGroup[] | undefined>(() => {
    if (view !== "list" || group === "none") return undefined;
    if (group === "type") {
      return [
        { key: "mcp", label: "MCP servers", color: MCP_COLOR },
        { key: "api", label: "OpenAPI", color: API_COLOR },
      ]
        .map((g) => ({
          ...g,
          items: sortConns(visibleConns.filter((e) => e.kind === g.key)).map(
            (e) => e.item
          ),
        }))
        .filter((g) => g.items.length > 0);
    }
    return STATUS_BUCKETS.map((b) => ({
      key: b.key,
      label: b.label,
      color: b.color,
      items: sortConns(visibleConns.filter((e) => b.match.includes(e.health))).map(
        (e) => e.item
      ),
    })).filter((g) => g.items.length > 0);
  }, [view, group, visibleConns, sortConns]);

  const mineItems = useMemo(
    () => sortConns(visibleConns).map((e) => e.item),
    [visibleConns, sortConns]
  );

  // ── tab counts (connections + specs, per the design) ──
  const counts = useMemo(() => {
    const mcpConns = connEntries.filter((e) => e.kind === "mcp").length;
    const apiConns = connEntries.filter((e) => e.kind === "api").length;
    const specs = specItems.length;
    return {
      all: mcpConns + apiConns + specs,
      mcp: mcpConns + specs,
      openapi: apiConns,
    };
  }, [connEntries, specItems.length]);

  // ── control handlers ──
  const onTab = (v: string) => {
    setTab(v as TabKey);
    syncUrl({ tab: v as TabKey });
  };
  const onView = (v: ViewKey) => {
    setView(v);
    setCookie("view_mcp-servers", v);
    syncUrl({ view: v });
  };
  const onGroup = (v: string) => {
    setGroup(v as GroupKey);
    syncUrl({ group: v as GroupKey });
  };
  const onOrder = (v: string) => {
    setOrder(v as OrderKey);
    syncUrl({ order: v as OrderKey });
  };
  const onSearch = (v: string) => {
    setSearch(v);
    syncUrl({ search: v });
  };
  const toggle = (key: string) =>
    setCollapsed((p) => ({ ...p, [key]: !p[key] }));

  const isEmpty =
    mcpInstances.length === 0 &&
    openApiConnections.length === 0 &&
    mcpServers.length === 0;

  return (
    <div className="collection-cq flex h-full w-full flex-col">
      <CollectionToolbar
        tabs={[
          { value: "all", label: "All", count: counts.all },
          { value: "mcp", label: "MCP", count: counts.mcp },
          { value: "openapi", label: "OpenAPI", count: counts.openapi },
        ]}
        activeTab={tab}
        onTabChange={onTab}
        searchSlot={
          <input
            value={search}
            onChange={(e) => onSearch(e.target.value)}
            placeholder={`${tCommon("search")}…`}
            className="h-7 w-full max-w-[260px] bg-transparent text-[12.5px] text-foreground outline-none placeholder:text-muted-foreground"
          />
        }
        displayLabel="Display"
        groupingLabel="Group connections"
        groupOptions={[
          { value: "none", label: "No grouping", icon: <Rows3 className="h-3.5 w-3.5" /> },
          { value: "status", label: "Status", icon: <Activity className="h-3.5 w-3.5" /> },
          { value: "type", label: "Type", icon: <Tag className="h-3.5 w-3.5" /> },
        ]}
        group={group}
        onGroupChange={onGroup}
        orderingLabel="Ordering"
        orderOptions={[
          { value: "name", label: "Name", icon: <ArrowDownAZ className="h-3.5 w-3.5" /> },
          { value: "status", label: "Status", icon: <Activity className="h-3.5 w-3.5" /> },
        ]}
        order={order}
        onOrderChange={onOrder}
        view={view}
        onViewChange={(v) => onView(v as ViewKey)}
        listLabel="List view"
        gridLabel="Grid view"
      />

      <div className="min-h-0 flex-1 overflow-auto">
        {isEmpty ? (
          <div className="p-4">
            <EmptyState
              title="No connections"
              description="No MCP servers or OpenAPI connections configured yet"
              iconsType="mcp"
            />
          </div>
        ) : (
          <>
            {/* SECTION 1 — My connections (always) */}
            <SectionHeader
              icon={<Check className="h-3 w-3" strokeWidth={2.4} />}
              name={t("myConnections")}
              count={visibleConns.length}
              sub="Configured in this workspace"
              variant={view}
              collapsed={!!collapsed.mine}
              onToggle={() => toggle("mine")}
            />
            {(view === "grid" || !collapsed.mine) && (
              <CollectionView
                view={view}
                containerQuery={false}
                gridClassName="px-4 pb-4"
                gridMinWidth={230}
                groups={mineGroups}
                items={mineGroups ? undefined : mineItems}
                emptyState={
                  <div className="px-4 py-3 text-[12px] text-muted-foreground">
                    {search
                      ? "No connections match this filter."
                      : "No connections configured yet."}
                  </div>
                }
              />
            )}

            {/* SECTION 2 — Browse MCP specifications (hidden for OpenAPI-only) */}
            {tab !== "openapi" && (
              <>
                <SectionHeader
                  icon={<Boxes className="h-3 w-3" strokeWidth={2} />}
                  name={t("browseSpecifications")}
                  count={visibleSpecs.length}
                  sub="Servers available to connect"
                  variant={view}
                  collapsed={!!collapsed.specs}
                  onToggle={() => toggle("specs")}
                />
                {(view === "grid" || !collapsed.specs) && (
                  <CollectionView
                    view={view}
                    containerQuery={false}
                    gridClassName="px-4 pb-4"
                    gridMinWidth={230}
                    items={visibleSpecs}
                    emptyState={
                      <div className="px-4 py-3 text-[12px] text-muted-foreground">
                        No specifications match this search.
                      </div>
                    }
                  />
                )}
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}
