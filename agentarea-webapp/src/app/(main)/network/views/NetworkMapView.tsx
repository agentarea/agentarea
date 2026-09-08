"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import {
  Background,
  BackgroundVariant,
  MarkerType,
  Panel,
  ReactFlow,
  type Edge,
  type Node,
  type ReactFlowInstance,
} from "@xyflow/react";
import { Focus, Minus, Plus, Search, X } from "lucide-react";
import "@xyflow/react/dist/style.css";
import type { EffectivePolicy } from "@/api/client/types.gen";
import { cn } from "@/lib/utils";
import DirectionalEdge from "../components/edges/DirectionalEdge";
import NetworkConnectionPanel from "../components/NetworkConnectionPanel";
import NetworkRegion, {
  type NetworkRegionData,
} from "../components/NetworkRegion";
import NetworkAgentNode, {
  type NetworkAgentData,
} from "../components/nodes/NetworkAgentNode";
import OrgChartNode from "../components/nodes/OrgChartNode";
import type {
  NetworkFlowNodeData,
  NetworkNodeData,
  TopologyResponse,
} from "../types";
import { getAccessTopology, type AccessScope } from "../utils/accessTopology";
import { buildDirectionalLayout } from "../utils/directionalLayout";
import { getDirectionalRoute } from "../utils/directionalRoute";
import { computeHighlightSets } from "../utils/highlight";
import {
  focusAgentTopology,
  getNetworkScope,
} from "../utils/networkConnections";
import {
  getAgentResources,
  NETWORK_AGENT_WIDTH,
  networkAgentHeight,
} from "../utils/networkMapLayout";
import {
  buildOrgChartLayout,
  ORG_NODE_HEIGHT,
  ORG_NODE_WIDTH,
} from "../utils/orgChartLayout";

export interface NetworkMapProps {
  mode?: "network" | "organization" | "access";
  topology: TopologyResponse;
  loadPolicy?: (agentId: string) => Promise<EffectivePolicy>;
  onNodeClick?: (node: NetworkNodeData) => void;
  highlightId?: string | null;
  onPaneClick?: () => void;
}

type MapNodeData = NetworkFlowNodeData | NetworkAgentData | NetworkRegionData;
const nodeTypes = {
  region: NetworkRegion,
  organization: OrgChartNode,
  networkAgent: NetworkAgentNode,
};
const edgeTypes = { directional: DirectionalEdge };
const fitOptions = { padding: 0.12, maxZoom: 1 };
const controlClass =
  "flex h-9 w-9 items-center justify-center text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary";

export default function NetworkMapView({
  mode = "network",
  topology,
  loadPolicy,
  onNodeClick,
  highlightId,
  onPaneClick,
}: NetworkMapProps) {
  const t = useTranslations("NetworkPage.orgChart");
  const flowText = useTranslations("NetworkPage.flowMap");
  const networkText = useTranslations("NetworkPage.networkMap");
  const isNetwork = mode === "network";
  const isAccess = mode === "access";
  const horizontal = mode !== "organization";
  const accessViewText = useTranslations("NetworkPage.accessView");
  const [accessScope, setAccessScope] = useState<AccessScope>("all");
  const mapTopology = useMemo(
    () => (isAccess ? getAccessTopology(topology, accessScope) : topology),
    [topology, isAccess, accessScope]
  );
  const accessText = useTranslations("NetworkPage.accessDetails");
  const [focusAgentId, setFocusAgentId] = useState<string | null>(null);
  const selectedNode = topology.nodes.find((node) => node.id === highlightId);
  const detailsOpen = !!selectedNode;
  const focusAgent = topology.nodes.find(
    (node) => node.id === focusAgentId && node.type === "agent"
  );
  const layoutTopology = useMemo(
    () =>
      focusAgentId
        ? focusAgentTopology(mapTopology, focusAgentId)
        : mapTopology,
    [mapTopology, focusAgentId]
  );
  const focusAgentPath = (agentId: string) => {
    setFocusAgentId(agentId);
    if (!isNetwork) setAgentsOnly(false);
    setQuery("");
  };
  const [expandedAgents, setExpandedAgents] = useState<Set<string>>(new Set());
  const resourcesByAgent = useMemo(
    () => getAgentResources(topology),
    [topology]
  );
  const [agentsOnly, setAgentsOnly] = useState(!isAccess);
  const clustered = isNetwork && agentsOnly;
  const summary = mode === "organization" && agentsOnly;
  const [query, setQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [flow, setFlow] = useState<ReactFlowInstance<
    Node<MapNodeData>,
    Edge
  > | null>(null);
  const [zoom, setZoom] = useState(1);
  const canvasRef = useRef<HTMLDivElement>(null);
  const layout = useMemo(
    () =>
      clustered
        ? buildDirectionalLayout(layoutTopology)
        : {
            regions: [],
            ...buildOrgChartLayout(
              layoutTopology,
              agentsOnly,
              (node) => ({
                width:
                  node.type === "agent" ? NETWORK_AGENT_WIDTH : ORG_NODE_WIDTH,
                height:
                  node.type === "agent" && summary
                    ? networkAgentHeight(
                        resourcesByAgent.get(node.id)?.length ?? 0,
                        expandedAgents.has(node.id)
                      )
                    : ORG_NODE_HEIGHT,
              }),
              horizontal ? { direction: "LR", aspectRatio: 2.4 } : undefined
            ),
          },
    [
      layoutTopology,
      agentsOnly,
      clustered,
      summary,
      horizontal,
      resourcesByAgent,
      expandedAgents,
    ]
  );
  const resourceConsumers = useMemo(() => {
    const counts = new Map<string, number>();
    for (const resources of resourcesByAgent.values())
      for (const resource of resources)
        counts.set(resource.node.id, resource.sharedBy);
    return counts;
  }, [resourcesByAgent]);
  const searchableNodes = useMemo(() => {
    const ids = new Set(layout.nodes.map((node) => node.id));
    if (summary)
      for (const resources of resourcesByAgent.values())
        for (const { node } of resources) ids.add(node.id);
    return topology.nodes.filter((node) => ids.has(node.id));
  }, [layout.nodes, summary, topology.nodes, resourcesByAgent]);
  const search = query.trim().toLocaleLowerCase();
  const matches = useMemo(
    () =>
      search
        ? searchableNodes.filter((node) =>
            node.label.toLocaleLowerCase().includes(search)
          )
        : [],
    [searchableNodes, search]
  );
  const matchIds = useMemo(() => {
    const ids = new Set(matches.map((node) => node.id));
    if (summary)
      for (const [agentId, resources] of resourcesByAgent)
        if (resources.some(({ node }) => ids.has(node.id))) ids.add(agentId);
    return ids;
  }, [matches, summary, resourcesByAgent]);
  const { nodes, edges } = useMemo(() => {
    const visibleSelection = layout.nodes.some(
      (node) => node.id === highlightId
    )
      ? highlightId
      : null;
    const highlight = computeHighlightSets(
      summary && topology.nodes.some((node) => node.id === highlightId)
        ? highlightId
        : visibleSelection,
      summary ? topology.edges : layout.edges
    );
    const entityNodes: Node<MapNodeData>[] = layout.nodes.map((node) => ({
      id: node.id,
      type: node.type === "agent" ? "networkAgent" : "organization",
      position: node.position,
      style: {
        width: node.type === "agent" ? NETWORK_AGENT_WIDTH : ORG_NODE_WIDTH,
        height: summary
          ? networkAgentHeight(
              resourcesByAgent.get(node.id)?.length ?? 0,
              expandedAgents.has(node.id)
            )
          : ORG_NODE_HEIGHT,
      },
      ariaLabel: `${node.label}, ${t(`types.${node.type}`)}`,
      data: {
        ...node,
        _horizontal: horizontal,
        _sharedBy: clustered ? resourceConsumers.get(node.id) : undefined,
        _targetTop: clustered,
        ...(node.type === "agent"
          ? {
              resources: resourcesByAgent.get(node.id) ?? [],
              showResources: summary,
              clustered,
              horizontal,
              expanded: expandedAgents.has(node.id),
              selectedResourceId: highlightId,
              onInspect: () =>
                onNodeClick?.(
                  topology.nodes.find((original) => original.id === node.id) ??
                    node
                ),
              onResourceClick: (resource: NetworkNodeData) =>
                onNodeClick?.(resource),
              onToggleResources: () =>
                setExpandedAgents((current) => {
                  const next = new Set(current);
                  if (next.has(node.id)) next.delete(node.id);
                  else next.add(node.id);
                  return next;
                }),
            }
          : {}),
        _highlighted: search
          ? matchIds.has(node.id)
          : node.id === visibleSelection ||
            (summary &&
              !!resourcesByAgent
                .get(node.id)
                ?.some((resource) => resource.node.id === highlightId)),
        _dimmed: search
          ? !matchIds.has(node.id)
          : !!highlight && !highlight.nodes.has(node.id),
      },
    }));
    const regions: Node<MapNodeData>[] = layout.regions.map((region) => ({
      id: region.id,
      type: "region",
      position: region.position,
      data: { kind: region.kind, count: region.count, label: region.label },
      style: {
        width: region.width,
        height: region.height,
        pointerEvents: "none",
      },
      selectable: false,
      focusable: false,
      draggable: false,
      connectable: false,
      zIndex:
        region.kind === "inputs" ||
        region.kind === "agents" ||
        region.kind === "outputs"
          ? -3
          : -2,
    }));
    const nodes = [...regions, ...entityNodes];
    const labelledRelations = new Set<string>();
    const edges: Edge[] = layout.edges.map((edge) => {
      const emphasized = !!highlight?.edges.has(edge.id);
      const delegation = edge.relation === "delegates_to";
      const route = clustered
        ? getDirectionalRoute(edge, layout.nodes, layout.regions)
        : undefined;
      const relationKey = `${edge.source}:${edge.relation}`;
      const showRelation =
        (emphasized || (!agentsOnly && layout.edges.length <= 16)) &&
        !labelledRelations.has(relationKey);
      if (showRelation) labelledRelations.add(relationKey);
      const color = emphasized
        ? "hsl(var(--primary))"
        : "hsl(var(--muted-foreground))";
      return {
        id: edge.id,
        source: edge.source,
        target: edge.target,
        sourceHandle: route?.sourceHandle,
        targetHandle: route?.targetHandle,
        data: route
          ? { points: route.points, labelPosition: route.label }
          : undefined,
        type: route ? "directional" : "smoothstep",
        pathOptions: { borderRadius: 12, offset: 24 },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          width: 14,
          height: 14,
          color,
        },
        style: {
          stroke: color,
          strokeWidth: emphasized ? 2 : 1.25,
          opacity:
            search || (highlight && !emphasized) ? 0.15 : emphasized ? 1 : 0.5,
          strokeDasharray: delegation ? undefined : "4 4",
        },
        label: showRelation
          ? t.has(`relations.${edge.relation}`)
            ? t(`relations.${edge.relation}`)
            : edge.relation
          : undefined,
        labelStyle: { fill: "hsl(var(--foreground))", fontSize: 11 },
        labelBgStyle: { fill: "hsl(var(--background))" },
        labelBgPadding: [6, 4] as [number, number],
        zIndex: emphasized ? 2 : 0,
      };
    });
    return { nodes, edges };
  }, [
    layout,
    highlightId,
    matchIds,
    search,
    t,
    summary,
    topology.edges,
    topology.nodes,
    resourcesByAgent,
    expandedAgents,
    onNodeClick,
    horizontal,
    agentsOnly,
    clustered,
    resourceConsumers,
  ]);

  useEffect(() => {
    if (!flow || !layout.nodes.length) return;
    const frame = requestAnimationFrame(() => {
      void flow.fitView(fitOptions);
    });
    return () => cancelAnimationFrame(frame);
  }, [flow, layout, detailsOpen]);

  useEffect(() => {
    if (!flow || !canvasRef.current) return;
    let frame = 0;
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        void flow.fitView(fitOptions);
      });
    });
    observer.observe(canvasRef.current);
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
    };
  }, [flow]);

  const selectResult = (node: NetworkNodeData) => {
    setQuery("");
    setSearchOpen(false);
    onNodeClick?.(topology.nodes.find((item) => item.id === node.id) ?? node);
    const focusIds =
      summary && node.type !== "agent"
        ? [...resourcesByAgent]
            .filter(([, resources]) =>
              resources.some((resource) => resource.node.id === node.id)
            )
            .map(([id]) => ({ id }))
        : [{ id: node.id }];
    void flow?.fitView({ nodes: focusIds, padding: 0.8, maxZoom: 1 });
  };

  return (
    <div className="flex h-full min-h-0 w-full flex-col bg-layoutBackground">
      <div className="relative z-10 flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-border bg-background px-4 py-3 md:px-5">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-foreground">
            {isAccess
              ? accessViewText("title")
              : isNetwork
                ? networkText("title")
                : t("title")}
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {isAccess
              ? accessViewText("description")
              : isNetwork
                ? agentsOnly
                  ? flowText("description")
                  : networkText("allDescription")
                : agentsOnly
                  ? t("agentDescription")
                  : t("allDescription")}
          </p>
        </div>
        {focusAgent && (
          <button
            type="button"
            onClick={() => setFocusAgentId(null)}
            className="flex max-w-full items-center gap-2 rounded-md border border-primary/20 bg-primary/5 px-2.5 py-1.5 text-xs text-primary"
            aria-label={accessText("clearFocus")}
          >
            <span className="truncate">
              {accessText("focusedOn", { name: focusAgent.label })}
            </span>
            <X className="h-3.5 w-3.5 shrink-0" />
          </button>
        )}
        <div className="flex w-full items-center gap-2 sm:w-auto">
          {isAccess ? (
            <select
              value={accessScope}
              aria-label={accessViewText("scopeFilter")}
              onChange={(event) => {
                setAccessScope(event.target.value as AccessScope);
                setFocusAgentId(null);
                setQuery("");
                onPaneClick?.();
              }}
              className="h-9 min-w-0 rounded-md border border-border bg-background px-2 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
            >
              {(["all", "private", "egress", "unknown"] as const).map(
                (scope) => (
                  <option key={scope} value={scope}>
                    {accessViewText(`scopes.${scope}`)}
                  </option>
                )
              )}
            </select>
          ) : (
            <div
              className="flex shrink-0 rounded-md border border-border bg-muted/50 p-0.5"
              role="group"
              aria-label={t("scope")}
            >
              {[true, false].map((value) => (
                <button
                  key={String(value)}
                  type="button"
                  aria-pressed={agentsOnly === value}
                  onClick={() => {
                    setAgentsOnly(value);
                    setFocusAgentId(null);
                    setQuery("");
                    onPaneClick?.();
                  }}
                  className={cn(
                    "rounded px-3 py-1.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary",
                    agentsOnly === value
                      ? "bg-background text-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground"
                  )}
                >
                  {isNetwork
                    ? value
                      ? networkText("overview")
                      : networkText("connections")
                    : value
                      ? t("agentsOnly")
                      : t("allResources")}
                </button>
              ))}
            </div>
          )}
          <div
            className="relative min-w-0 flex-1 sm:w-64"
            onBlur={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget))
                setSearchOpen(false);
            }}
          >
            <Search className="pointer-events-none absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
            <input
              aria-label={networkText("search")}
              placeholder={networkText("search")}
              value={query}
              onFocus={() => setSearchOpen(true)}
              onChange={(event) => {
                setQuery(event.target.value);
                setSearchOpen(true);
              }}
              onKeyDown={(event) => {
                if (event.key === "Escape") {
                  setQuery("");
                  setSearchOpen(false);
                }
                if (event.key === "Enter" && matches[0])
                  selectResult(matches[0]);
              }}
              className="h-9 w-full rounded-md border border-border bg-background pl-8 pr-7 text-xs outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-primary"
            />
            {query && (
              <button
                type="button"
                aria-label={t("clearSearch")}
                onClick={() => setQuery("")}
                className="absolute right-1 top-1 flex h-7 w-6 items-center justify-center rounded text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-primary"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
            {search && searchOpen && (
              <div className="absolute right-0 top-11 z-20 max-h-64 w-64 max-w-[calc(100vw-2rem)] overflow-auto rounded-lg border border-border bg-popover p-1 shadow-lg">
                <p
                  className="px-2 py-2 text-xs text-muted-foreground"
                  role="status"
                >
                  {t("matches", { count: matches.length })}
                </p>
                {matches.map((node) => (
                  <button
                    type="button"
                    key={node.id}
                    onClick={() => selectResult(node)}
                    className="block w-full rounded px-2 py-2 text-left text-xs hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                  >
                    <span className="block truncate font-medium">
                      {node.label}
                    </span>
                    <span className="mt-0.5 block text-muted-foreground">
                      {t(`types.${node.type}`)}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <div ref={canvasRef} className="relative min-h-0 flex-1">
          {nodes.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center">
              <p className="text-sm font-medium">
                {isAccess ? accessViewText("empty") : t("noAgents")}
              </p>
              {!isAccess && (
                <button
                  type="button"
                  onClick={() => setAgentsOnly(false)}
                  className="rounded text-xs text-primary underline underline-offset-4 focus-visible:ring-2 focus-visible:ring-primary"
                >
                  {t("showResources")}
                </button>
              )}
            </div>
          ) : (
            <ReactFlow
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              edgeTypes={edgeTypes}
              onInit={setFlow}
              nodesDraggable={false}
              nodesConnectable={false}
              edgesFocusable={false}
              fitView
              fitViewOptions={fitOptions}
              minZoom={0.1}
              maxZoom={1.8}
              onMove={(_, viewport) => setZoom(viewport.zoom)}
              onPaneClick={() => {
                setSearchOpen(false);
                onPaneClick?.();
              }}
              onNodeClick={(_, node) => {
                const original = topology.nodes.find(
                  (item) => item.id === node.id
                );
                if (original) onNodeClick?.(original);
              }}
              className="[&_.react-flow__node:focus-visible]:outline [&_.react-flow__node:focus-visible]:outline-2 [&_.react-flow__node:focus-visible]:outline-primary"
              aria-label={
                isAccess
                  ? accessViewText("title")
                  : isNetwork
                    ? networkText("title")
                    : t("title")
              }
            >
              <Background
                variant={BackgroundVariant.Dots}
                gap={24}
                size={1}
                color="hsl(var(--border))"
              />
              <Panel
                position="bottom-left"
                className="!m-4 flex items-center overflow-hidden rounded-lg border border-border bg-background shadow-sm"
              >
                <button
                  type="button"
                  className={controlClass}
                  onClick={() => void flow?.zoomOut()}
                  aria-label={t("zoomOut")}
                >
                  <Minus className="h-4 w-4" />
                </button>
                <span
                  className="w-12 text-center text-xs tabular-nums text-muted-foreground"
                  aria-label={t("zoomLevel")}
                >
                  {Math.round(zoom * 100)}%
                </span>
                <button
                  type="button"
                  className={controlClass}
                  onClick={() => void flow?.zoomIn()}
                  aria-label={t("zoomIn")}
                >
                  <Plus className="h-4 w-4" />
                </button>
                <span className="h-5 w-px bg-border" />
                <button
                  type="button"
                  className={controlClass}
                  onClick={() => void flow?.fitView(fitOptions)}
                  aria-label={t("fitView")}
                  title={t("fitView")}
                >
                  <Focus className="h-4 w-4" />
                </button>
              </Panel>
            </ReactFlow>
          )}
        </div>
        {selectedNode && (
          <NetworkConnectionPanel
            key={selectedNode.id}
            node={selectedNode}
            topology={topology}
            onSelect={(node) => {
              if (
                isAccess &&
                accessScope !== "all" &&
                node.type !== "agent" &&
                getNetworkScope(node) !== accessScope
              )
                setAccessScope("all");
              if (
                focusAgentId &&
                !layoutTopology.nodes.some((item) => item.id === node.id)
              )
                setFocusAgentId(null);
              onNodeClick?.(node);
            }}
            onClose={() => onPaneClick?.()}
            onFocus={focusAgentPath}
            loadPolicy={loadPolicy}
          />
        )}
      </div>
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-x-4 gap-y-2 border-t border-border bg-background px-4 py-2.5 text-xs text-muted-foreground md:px-5">
        <div className="flex items-center gap-4">
          <span className="tabular-nums">
            {summary
              ? networkText("visibleAgents", { count: layout.nodes.length })
              : t("visibleNodes", { count: layout.nodes.length })}
          </span>
          <span className="flex items-center gap-2">
            <span className="h-px w-5 bg-muted-foreground" />
            {t("delegation")}
          </span>
          {(!agentsOnly || clustered) && (
            <span className="flex items-center gap-2">
              <span className="w-5 border-t border-dashed border-muted-foreground" />
              {t("resourceLink")}
            </span>
          )}
        </div>
        <span className="hidden lg:inline">{accessText("mapHint")}</span>
      </div>
    </div>
  );
}
