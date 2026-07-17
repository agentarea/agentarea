"use client";

import { useMemo, type MouseEventHandler } from "react";
import {
  Bot,
  Cable,
  CircleSlash,
  GitBranch,
  Globe2,
  KeyRound,
  LockKeyhole,
  Network,
  Plug,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { NetworkNodeData, TopologyResponse } from "../types";

interface Props {
  topology: TopologyResponse;
  onNodeClick?: (node: NetworkNodeData) => void;
  highlightId?: string | null;
  onPaneClick?: () => void;
}

type AccessNodeKind = "agent" | "mcp" | "openapi" | "skill";
type AccessRelation = "mcp" | "openapi" | "skill" | "delegates";
type ResourceScope = "private" | "egress" | "external";

interface GraphNode {
  id: string;
  source: NetworkNodeData;
  kind: "agent" | "resource";
  x: number;
  y: number;
  width: number;
  height: number;
  highlighted: boolean;
  dimmed: boolean;
  egress?: boolean;
  mcpCount?: number;
  delegateCount?: number;
  resourceKind?: AccessNodeKind;
  scope?: ResourceScope;
  consumerCount?: number;
}

interface GraphEdge {
  id: string;
  sourceId: string;
  targetId: string;
  relation: AccessRelation;
  label: string;
  source: GraphNode;
  target: GraphNode;
  highlighted: boolean;
  dimmed: boolean;
}

const AGENT_W = 248;
const RESOURCE_W = 230;
const NODE_H = 86;
const ROW_GAP = 132;
const GRAPH_TOP = 154;
const GRAPH_PAD = 48;

const GRAPH_X = {
  agents: 56,
  private: 452,
  external: 820,
};

const ZONES = [
  {
    id: "agents",
    title: "Agents",
    subtitle: "Execution identities and delegation paths",
    x: GRAPH_X.agents - 36,
    width: 320,
    tone: "blue" as const,
  },
  {
    id: "private",
    title: "Private access",
    subtitle: "Internal MCP and non-egress resources",
    x: GRAPH_X.private - 36,
    width: 300,
    tone: "slate" as const,
  },
  {
    id: "external",
    title: "External / egress",
    subtitle: "Anything that can leave the workspace boundary",
    x: GRAPH_X.external - 36,
    width: 300,
    tone: "violet" as const,
  },
];

function isEgressResource(node: NetworkNodeData) {
  if (node.type === "openapi_connection") return true;
  return String(node.metadata?.network_scope ?? "").toLowerCase() === "egress";
}

function relationLabel(relation: string) {
  if (relation === "uses_mcp") return "MCP";
  if (relation === "uses_openapi") return "OpenAPI";
  if (relation === "has_skill") return "Skill";
  if (relation === "delegates_to") return "Delegates";
  return relation.replaceAll("_", " ");
}

function median(values: number[]) {
  if (values.length === 0) return GRAPH_TOP;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0
    ? (sorted[mid - 1] + sorted[mid]) / 2
    : sorted[mid];
}

function staggerByDesiredY<
  T extends { id: string; desiredY: number; label: string },
>(items: T[], minGap = ROW_GAP) {
  let lastY = GRAPH_TOP - minGap;
  return [...items]
    .sort((a, b) =>
      a.desiredY === b.desiredY
        ? a.label.localeCompare(b.label)
        : a.desiredY - b.desiredY
    )
    .map((item) => {
      const y = Math.max(item.desiredY, lastY + minGap);
      lastY = y;
      return { ...item, y };
    });
}

function toRelation(relation: string): AccessRelation {
  if (relation === "delegates_to") return "delegates";
  if (relation === "uses_openapi") return "openapi";
  if (relation === "has_skill") return "skill";
  return "mcp";
}

export default function AccessGraphView({
  topology,
  onNodeClick,
  highlightId,
  onPaneClick,
}: Props) {
  const graph = useMemo(() => {
    const nodesById = new Map(topology.nodes.map((node) => [node.id, node]));
    const agents = topology.nodes
      .filter((node) => node.type === "agent")
      .sort((a, b) => a.label.localeCompare(b.label));
    const agentY = new Map(
      agents.map((agent, index) => [agent.id, GRAPH_TOP + index * ROW_GAP])
    );

    const accessEdges = topology.edges.filter((edge) =>
      ["uses_mcp", "uses_openapi", "has_skill", "delegates_to"].includes(
        edge.relation
      )
    );

    const resources = topology.nodes.filter(
      (node) =>
        node.type === "mcp_instance" ||
        node.type === "openapi_connection" ||
        node.type === "skill"
    );

    const resourceConsumerY = new Map<string, number[]>();
    for (const edge of accessEdges) {
      const target = nodesById.get(edge.target);
      if (!target || target.type === "agent") continue;
      const y = agentY.get(edge.source);
      if (y === undefined) continue;
      const list = resourceConsumerY.get(edge.target) ?? [];
      list.push(y);
      resourceConsumerY.set(edge.target, list);
    }

    const privateResources = resources
      .filter((node) => !isEgressResource(node))
      .map((node) => ({
        id: node.id,
        label: node.label,
        desiredY: median(resourceConsumerY.get(node.id) ?? []),
      }));
    const externalResources = resources
      .filter((node) => isEgressResource(node))
      .map((node) => ({
        id: node.id,
        label: node.label,
        desiredY: median(resourceConsumerY.get(node.id) ?? []),
      }));

    const privateY = new Map(
      staggerByDesiredY(privateResources).map((item) => [item.id, item.y])
    );
    const externalY = new Map(
      staggerByDesiredY(externalResources).map((item) => [item.id, item.y])
    );

    const mcpAccessByAgent = new Map<string, number>();
    const delegationByAgent = new Map<string, number>();
    const egressByAgent = new Map<string, boolean>();

    for (const edge of accessEdges) {
      const target = nodesById.get(edge.target);
      if (edge.relation === "uses_mcp") {
        mcpAccessByAgent.set(
          edge.source,
          (mcpAccessByAgent.get(edge.source) ?? 0) + 1
        );
      }
      if (edge.relation === "delegates_to") {
        delegationByAgent.set(
          edge.source,
          (delegationByAgent.get(edge.source) ?? 0) + 1
        );
      }
      if (target && target.type !== "agent" && isEgressResource(target)) {
        egressByAgent.set(edge.source, true);
      }
    }

    const connectedToHighlight = (id: string) =>
      !highlightId ||
      id === highlightId ||
      accessEdges.some(
        (edge) =>
          (edge.source === highlightId && edge.target === id) ||
          (edge.target === highlightId && edge.source === id)
      );

    const graphNodes = new Map<string, GraphNode>();
    for (const agent of agents) {
      const highlighted = agent.id === highlightId;
      graphNodes.set(agent.id, {
        id: agent.id,
        source: agent,
        kind: "agent",
        x: GRAPH_X.agents,
        y: agentY.get(agent.id) ?? GRAPH_TOP,
        width: AGENT_W,
        height: NODE_H,
        highlighted,
        dimmed: !!highlightId && !connectedToHighlight(agent.id),
        egress: egressByAgent.get(agent.id) ?? false,
        mcpCount: mcpAccessByAgent.get(agent.id) ?? 0,
        delegateCount: delegationByAgent.get(agent.id) ?? 0,
      });
    }

    for (const resource of resources) {
      const external = isEgressResource(resource);
      const highlighted = resource.id === highlightId;
      graphNodes.set(resource.id, {
        id: resource.id,
        source: resource,
        kind: "resource",
        x: external ? GRAPH_X.external : GRAPH_X.private,
        y: (external ? externalY : privateY).get(resource.id) ?? GRAPH_TOP,
        width: RESOURCE_W,
        height: NODE_H,
        highlighted,
        dimmed: !!highlightId && !connectedToHighlight(resource.id),
        resourceKind:
          resource.type === "mcp_instance"
            ? "mcp"
            : resource.type === "openapi_connection"
              ? "openapi"
              : "skill",
        scope:
          resource.type === "openapi_connection"
            ? "external"
            : external
              ? "egress"
              : "private",
        consumerCount: resourceConsumerY.get(resource.id)?.length ?? 0,
      });
    }

    const graphEdges: GraphEdge[] = [];
    for (const edge of accessEdges) {
      const source = graphNodes.get(edge.source);
      const target = graphNodes.get(edge.target);
      if (!source || !target) continue;
      const highlighted =
        edge.source === highlightId || edge.target === highlightId;
      graphEdges.push({
        id: edge.id,
        sourceId: edge.source,
        targetId: edge.target,
        source,
        target,
        relation: toRelation(edge.relation),
        label: relationLabel(edge.relation),
        highlighted,
        dimmed: !!highlightId && !highlighted,
      });
    }

    const maxY = Math.max(
      GRAPH_TOP,
      ...Array.from(graphNodes.values()).map((node) => node.y)
    );
    const height = maxY + NODE_H + GRAPH_PAD;
    const width = GRAPH_X.external + RESOURCE_W + GRAPH_PAD;
    const egressAgents = Array.from(egressByAgent.values()).filter(
      Boolean
    ).length;
    const mcpEdges = accessEdges.filter(
      (edge) => edge.relation === "uses_mcp"
    ).length;
    const delegationEdges = accessEdges.filter(
      (edge) => edge.relation === "delegates_to"
    ).length;

    return {
      nodes: Array.from(graphNodes.values()),
      edges: graphEdges,
      height,
      width,
      stats: {
        agents: agents.length,
        egressAgents,
        noEgressAgents: agents.length - egressAgents,
        mcpEdges,
        delegationEdges,
      },
    };
  }, [topology, highlightId]);

  return (
    <div className="relative h-full w-full overflow-hidden bg-[#f8fafc] dark:bg-zinc-950">
      <BlueprintBackground />
      <div className="pointer-events-none absolute left-4 top-4 z-20 flex max-w-[calc(100%-2rem)] flex-wrap gap-2">
        <div className="rounded-lg border border-blue-100/80 bg-white/90 px-4 py-3 shadow-[0_18px_60px_rgba(15,23,42,0.08)] backdrop-blur-xl dark:border-blue-900/50 dark:bg-zinc-950/85">
          <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-blue-600 dark:text-blue-300">
            Access Graph
          </p>
          <p className="mt-1 max-w-[340px] text-xs leading-snug text-zinc-500 dark:text-zinc-400">
            Agents, outbound access, MCP usage, and delegation paths.
          </p>
        </div>
        <GraphStat label="Agents" value={graph.stats.agents} icon={Bot} />
        <GraphStat
          label="Can egress"
          value={graph.stats.egressAgents}
          icon={Cable}
        />
        <GraphStat
          label="No egress"
          value={graph.stats.noEgressAgents}
          icon={CircleSlash}
        />
        <GraphStat label="MCP links" value={graph.stats.mcpEdges} icon={Plug} />
        <GraphStat
          label="Delegations"
          value={graph.stats.delegationEdges}
          icon={GitBranch}
        />
      </div>

      <div
        className="relative h-full w-full overflow-auto"
        onClick={onPaneClick}
      >
        <div
          className="relative"
          style={{
            width: graph.width,
            height: graph.height,
            minHeight: "100%",
          }}
        >
          {ZONES.map((zone) => (
            <AccessZone
              key={zone.id}
              height={Math.max(graph.height - GRAPH_TOP + 92, 320)}
              subtitle={zone.subtitle}
              title={zone.title}
              tone={zone.tone}
              width={zone.width}
              x={zone.x}
              y={GRAPH_TOP - 84}
            />
          ))}

          <svg
            className="pointer-events-none absolute inset-0 z-10"
            height={graph.height}
            width={graph.width}
          >
            <defs>
              <marker
                id="access-arrow-slate"
                markerHeight="7"
                markerWidth="7"
                orient="auto"
                refX="6"
                refY="3.5"
              >
                <path d="M0,0 L0,7 L7,3.5 z" fill="#475569" />
              </marker>
              <marker
                id="access-arrow-blue"
                markerHeight="7"
                markerWidth="7"
                orient="auto"
                refX="6"
                refY="3.5"
              >
                <path d="M0,0 L0,7 L7,3.5 z" fill="#0ea5e9" />
              </marker>
              <marker
                id="access-arrow-violet"
                markerHeight="7"
                markerWidth="7"
                orient="auto"
                refX="6"
                refY="3.5"
              >
                <path d="M0,0 L0,7 L7,3.5 z" fill="#7c3aed" />
              </marker>
            </defs>
            {graph.edges.map((edge) => (
              <AccessEdge key={edge.id} edge={edge} />
            ))}
          </svg>

          <div className="absolute inset-0 z-20">
            {graph.nodes.map((node) =>
              node.kind === "agent" ? (
                <AgentCard
                  key={node.id}
                  node={node}
                  onClick={(event) => {
                    event.stopPropagation();
                    onNodeClick?.(node.source);
                  }}
                />
              ) : (
                <ResourceCard
                  key={node.id}
                  node={node}
                  onClick={(event) => {
                    event.stopPropagation();
                    onNodeClick?.(node.source);
                  }}
                />
              )
            )}
          </div>
        </div>
      </div>

      <div className="pointer-events-none absolute bottom-4 right-4 z-30 rounded-lg border border-zinc-200/80 bg-white/90 p-3 shadow-[0_18px_60px_rgba(15,23,42,0.08)] backdrop-blur-xl dark:border-zinc-800 dark:bg-zinc-950/85">
        <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-zinc-700 dark:text-zinc-200">
          Edge key
        </p>
        <div className="mt-2 grid gap-1.5 text-[10px] text-zinc-600 dark:text-zinc-400">
          <LegendItem className="bg-slate-500" label="MCP/private access" />
          <LegendItem className="bg-violet-500" label="OpenAPI / egress" />
          <LegendItem className="bg-sky-500" label="Skill access" />
          <LegendItem
            className="border border-sky-500 bg-white"
            label="Delegates"
          />
        </div>
      </div>
    </div>
  );
}

function BlueprintBackground() {
  return (
    <div
      className="pointer-events-none absolute inset-0 opacity-80 dark:opacity-30"
      style={{
        backgroundImage:
          "linear-gradient(rgba(37,99,235,0.08) 1px, transparent 1px), linear-gradient(90deg, rgba(37,99,235,0.08) 1px, transparent 1px), radial-gradient(circle at 72% 20%, rgba(124,58,237,0.10), transparent 28%)",
        backgroundSize: "32px 32px, 32px 32px, auto",
      }}
    />
  );
}

function AccessZone({
  title,
  subtitle,
  tone,
  x,
  y,
  width,
  height,
}: {
  title: string;
  subtitle: string;
  tone: "blue" | "slate" | "violet";
  x: number;
  y: number;
  width: number;
  height: number;
}) {
  const toneClass =
    tone === "blue"
      ? "border-blue-300/70 bg-blue-50/20 text-blue-700 dark:border-blue-800/60 dark:bg-blue-950/10 dark:text-blue-300"
      : tone === "violet"
        ? "border-violet-300/70 bg-violet-50/20 text-violet-700 dark:border-violet-800/60 dark:bg-violet-950/10 dark:text-violet-300"
        : "border-slate-300/80 bg-white/35 text-slate-700 dark:border-slate-700/70 dark:bg-slate-950/20 dark:text-slate-300";

  return (
    <div
      className={cn(
        "pointer-events-none absolute z-0 overflow-hidden rounded-lg border border-dashed shadow-[inset_0_1px_0_rgba(255,255,255,0.8)]",
        toneClass
      )}
      style={{ height, left: x, top: y, width }}
    >
      <div className="absolute inset-0 opacity-45 [background-image:linear-gradient(rgba(37,99,235,0.10)_1px,transparent_1px),linear-gradient(90deg,rgba(37,99,235,0.10)_1px,transparent_1px)] [background-size:24px_24px]" />
      <div className="relative px-4 pt-4">
        <p className="text-[10px] font-semibold uppercase tracking-[0.18em]">
          {title}
        </p>
        <p className="mt-1 text-[10px] leading-tight text-zinc-500 dark:text-zinc-400">
          {subtitle}
        </p>
      </div>
    </div>
  );
}

function AgentCard({
  node,
  onClick,
}: {
  node: GraphNode;
  onClick: MouseEventHandler<HTMLButtonElement>;
}) {
  const egress = node.egress ?? false;
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "absolute z-20 rounded-lg border bg-white/95 p-3 text-left shadow-[0_16px_44px_rgba(15,23,42,0.10)] ring-4 ring-transparent backdrop-blur transition-all hover:-translate-y-0.5 hover:shadow-[0_20px_52px_rgba(15,23,42,0.14)] focus-visible:outline-none focus-visible:ring-blue-200 dark:bg-zinc-950/90",
        egress
          ? "border-blue-300 dark:border-blue-800"
          : "border-zinc-200 dark:border-zinc-700",
        node.highlighted && "ring-blue-200 dark:ring-blue-900/70",
        node.dimmed && !node.highlighted && "opacity-25"
      )}
      style={{
        height: node.height,
        left: node.x,
        top: node.y,
        width: node.width,
      }}
    >
      <div
        className={cn(
          "absolute inset-x-0 top-0 h-0.5",
          egress ? "bg-blue-500" : "bg-zinc-300"
        )}
      />
      <div className="flex items-start gap-3">
        <div
          className={cn(
            "flex h-10 w-10 shrink-0 items-center justify-center rounded-md border shadow-sm",
            egress
              ? "border-blue-100 bg-blue-50 text-blue-600 dark:border-blue-900 dark:bg-blue-950/50 dark:text-blue-300"
              : "border-zinc-200 bg-zinc-50 text-zinc-600 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300"
          )}
        >
          <Bot className="h-5 w-5" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start gap-2">
            <p className="min-w-0 flex-1 truncate text-sm font-semibold leading-tight text-zinc-950 dark:text-zinc-50">
              {node.source.label}
            </p>
            <span
              className={cn(
                "shrink-0 rounded-full px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.12em] ring-1",
                egress
                  ? "bg-blue-50 text-blue-700 ring-blue-100 dark:bg-blue-950/50 dark:text-blue-300 dark:ring-blue-900/70"
                  : "bg-zinc-100 text-zinc-600 ring-zinc-200 dark:bg-zinc-900 dark:text-zinc-300 dark:ring-zinc-700"
              )}
            >
              {egress ? "egress" : "no egress"}
            </span>
          </div>
          <p className="mt-1 truncate text-[10px] font-medium uppercase tracking-[0.14em] text-zinc-500 dark:text-zinc-400">
            Agent · {node.source.status || "active"}
          </p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <span className="inline-flex items-center gap-1 rounded-md bg-zinc-50 px-1.5 py-0.5 text-[10px] text-zinc-600 ring-1 ring-zinc-200 dark:bg-zinc-900 dark:text-zinc-300 dark:ring-zinc-700">
              <Plug className="h-3 w-3" />
              {node.mcpCount ?? 0} MCP
            </span>
            <span className="inline-flex items-center gap-1 rounded-md bg-zinc-50 px-1.5 py-0.5 text-[10px] text-zinc-600 ring-1 ring-zinc-200 dark:bg-zinc-900 dark:text-zinc-300 dark:ring-zinc-700">
              <GitBranch className="h-3 w-3" />
              {node.delegateCount ?? 0} delegates
            </span>
          </div>
        </div>
      </div>
    </button>
  );
}

function ResourceCard({
  node,
  onClick,
}: {
  node: GraphNode;
  onClick: MouseEventHandler<HTMLButtonElement>;
}) {
  const scope = node.scope ?? "private";
  const isExternal = scope === "egress" || scope === "external";
  const Icon =
    node.resourceKind === "mcp"
      ? Plug
      : node.resourceKind === "openapi"
        ? Globe2
        : node.resourceKind === "skill"
          ? Sparkles
          : Network;

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "absolute z-20 rounded-lg border bg-white/[0.92] p-3 text-left shadow-[0_14px_40px_rgba(15,23,42,0.08)] ring-4 ring-transparent backdrop-blur transition-all hover:-translate-y-0.5 hover:shadow-[0_20px_48px_rgba(15,23,42,0.12)] focus-visible:outline-none focus-visible:ring-blue-200 dark:bg-zinc-950/90",
        isExternal
          ? "border-violet-200 dark:border-violet-800/80"
          : "border-slate-200 dark:border-slate-700/80",
        node.highlighted && "ring-blue-200 dark:ring-blue-900/70",
        node.dimmed && !node.highlighted && "opacity-25"
      )}
      style={{
        height: node.height,
        left: node.x,
        top: node.y,
        width: node.width,
      }}
    >
      <div
        className={cn(
          "absolute inset-x-0 top-0 h-0.5",
          isExternal ? "bg-violet-400" : "bg-slate-400"
        )}
      />
      <div className="flex items-start gap-3">
        <div
          className={cn(
            "flex h-9 w-9 shrink-0 items-center justify-center rounded-md border shadow-sm",
            isExternal
              ? "border-violet-100 bg-violet-50 text-violet-600 dark:border-violet-900 dark:bg-violet-950/50 dark:text-violet-300"
              : "border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300"
          )}
        >
          <Icon className="h-[18px] w-[18px]" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold leading-tight text-zinc-950 dark:text-zinc-50">
            {node.source.label}
          </p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <span
              className={cn(
                "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-medium ring-1",
                isExternal
                  ? "bg-violet-50 text-violet-700 ring-violet-100 dark:bg-violet-950/40 dark:text-violet-300 dark:ring-violet-900/70"
                  : "bg-slate-50 text-slate-700 ring-slate-200 dark:bg-slate-900 dark:text-slate-300 dark:ring-slate-700"
              )}
            >
              {isExternal ? (
                <Cable className="h-3 w-3" />
              ) : (
                <LockKeyhole className="h-3 w-3" />
              )}
              {scope}
            </span>
            <span className="inline-flex items-center gap-1 rounded-md bg-white px-1.5 py-0.5 text-[10px] text-zinc-500 ring-1 ring-zinc-200 dark:bg-zinc-900 dark:text-zinc-400 dark:ring-zinc-700">
              <KeyRound className="h-3 w-3" />
              {node.consumerCount ?? 0} agents
            </span>
          </div>
        </div>
      </div>
    </button>
  );
}

function AccessEdge({ edge }: { edge: GraphEdge }) {
  const palette =
    edge.relation === "delegates"
      ? {
          marker: "access-arrow-blue",
          stroke: "#0ea5e9",
          fill: "#e0f2fe",
          text: "#0369a1",
        }
      : edge.relation === "openapi"
        ? {
            marker: "access-arrow-violet",
            stroke: "#7c3aed",
            fill: "#f5f3ff",
            text: "#6d28d9",
          }
        : edge.relation === "skill"
          ? {
              marker: "access-arrow-blue",
              stroke: "#0284c7",
              fill: "#e0f2fe",
              text: "#0369a1",
            }
          : {
              marker: "access-arrow-slate",
              stroke: "#475569",
              fill: "#f8fafc",
              text: "#334155",
            };

  const points =
    edge.relation === "delegates" ? delegationPoints(edge) : accessPoints(edge);

  return (
    <g opacity={edge.dimmed ? 0.22 : 1}>
      <path
        d={points.path}
        fill="none"
        stroke="#ffffff"
        strokeOpacity={0.72}
        strokeWidth={6}
      />
      <path
        d={points.path}
        fill="none"
        markerEnd={`url(#${palette.marker})`}
        stroke={palette.stroke}
        strokeDasharray={edge.relation === "delegates" ? "6,5" : undefined}
        strokeLinecap="round"
        strokeOpacity={edge.highlighted ? 1 : 0.78}
        strokeWidth={edge.highlighted ? 2.2 : 1.6}
      />
      <foreignObject
        height={24}
        width={104}
        x={points.labelX - 52}
        y={points.labelY - 12}
      >
        <div className="flex h-6 items-center justify-center">
          <span
            className="rounded-full border border-white/80 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.12em] shadow-sm"
            style={{ background: palette.fill, color: palette.text }}
          >
            {edge.label}
          </span>
        </div>
      </foreignObject>
    </g>
  );
}

function accessPoints(edge: GraphEdge) {
  const sx = edge.source.x + edge.source.width;
  const sy = edge.source.y + edge.source.height / 2;
  const tx = edge.target.x;
  const ty = edge.target.y + edge.target.height / 2;
  const dx = Math.max((tx - sx) * 0.44, 90);
  return {
    labelX: (sx + tx) / 2,
    labelY: (sy + ty) / 2,
    path: `M ${sx} ${sy} C ${sx + dx} ${sy}, ${tx - dx} ${ty}, ${tx} ${ty}`,
  };
}

function delegationPoints(edge: GraphEdge) {
  const sourceBelow = edge.target.y > edge.source.y;
  const sx = edge.source.x + edge.source.width / 2;
  const sy = sourceBelow ? edge.source.y + edge.source.height : edge.source.y;
  const tx = edge.target.x + edge.target.width / 2;
  const ty = sourceBelow ? edge.target.y : edge.target.y + edge.target.height;
  const sideX = edge.source.x - 54;
  const bend = sourceBelow ? 58 : -58;
  return {
    labelX: sideX,
    labelY: (sy + ty) / 2,
    path: `M ${sx} ${sy} C ${sideX} ${sy + bend}, ${sideX} ${ty - bend}, ${tx} ${ty}`,
  };
}

function GraphStat({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: number;
  icon: LucideIcon;
}) {
  return (
    <div className="rounded-lg border border-zinc-200/80 bg-white/90 px-3 py-2 shadow-sm backdrop-blur dark:border-zinc-800 dark:bg-zinc-950/85">
      <div className="flex items-center gap-2">
        <Icon className="h-3.5 w-3.5 text-blue-500" />
        <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-zinc-500">
          {label}
        </span>
      </div>
      <p className="mt-1 text-base font-semibold leading-none text-zinc-950 dark:text-zinc-50">
        {value}
      </p>
    </div>
  );
}

function LegendItem({
  className,
  label,
}: {
  className: string;
  label: string;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className={cn("h-1.5 w-6 rounded-full", className)} />
      <span>{label}</span>
    </div>
  );
}
