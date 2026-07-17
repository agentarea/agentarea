"use client";

import { useMemo } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  ReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import DataFlowEdge from "../components/edges/DataFlowEdge";
import LaneRail from "../components/LaneRail";
import AgentNode from "../components/nodes/AgentNode";
import MCPNode from "../components/nodes/MCPNode";
import OpenAPINode from "../components/nodes/OpenAPINode";
import SkillNode from "../components/nodes/SkillNode";
import TriggerNode from "../components/nodes/TriggerNode";
import type { NetworkNodeData, TopologyResponse } from "../types";
import { layoutClusters, type Lane } from "../utils/clusterLayout";
import { computeHighlightSets } from "../utils/highlight";

interface Props {
  topology: TopologyResponse;
  onNodeClick?: (node: NetworkNodeData) => void;
  highlightId?: string | null;
  onPaneClick?: () => void;
}

const nodeTypes = {
  agent: AgentNode,
  mcp_instance: MCPNode,
  openapi_connection: OpenAPINode,
  skill: SkillNode,
  trigger: TriggerNode,
  lane: LaneRail,
};

const edgeTypes = {
  dataflow: DataFlowEdge,
};

const LANE_X: Record<Lane, number> = {
  events: 0,
  agents: 420,
  external: 840,
};

type LaneTone = "blue" | "neutral" | "rose";

const LANE_META: Record<
  Lane,
  { label: string; sublabel: string; tone: LaneTone; iconKey: Lane }
> = {
  events: {
    label: "Events",
    sublabel: "Triggers · webhooks · schedules",
    tone: "blue",
    iconKey: "events",
  },
  agents: {
    label: "Agents",
    sublabel: "Internal — governed",
    tone: "neutral",
    iconKey: "agents",
  },
  external: {
    label: "External",
    sublabel: "MCP · OpenAPI · skills",
    tone: "rose",
    iconKey: "external",
  },
};

const ROW_H = 164;
const CLUSTER_GAP = 104;
const NODE_HALF_W = 104;
const LANE_PAD = 64;
const LANE_HEADER = 92;

export default function DataFlowView({
  topology,
  onNodeClick,
  highlightId,
  onPaneClick,
}: Props) {
  const { nodes, edges, visibleCount, clusterCount } = useMemo(() => {
    const visibleNodes = topology.nodes.filter(
      (n) =>
        n.type === "agent" ||
        n.type === "mcp_instance" ||
        n.type === "openapi_connection" ||
        n.type === "skill" ||
        n.type === "trigger"
    );
    const nodeIds = new Set(visibleNodes.map((n) => n.id));
    const validEdges = topology.edges.filter(
      (e) => nodeIds.has(e.source) && nodeIds.has(e.target)
    );

    const { positions, clusters } = layoutClusters(
      visibleNodes.map((n) => ({ id: n.id, type: n.type, label: n.label })),
      validEdges,
      {
        laneX: LANE_X,
        rowHeight: ROW_H,
        clusterGap: CLUSTER_GAP,
      }
    );

    const highlight = computeHighlightSets(highlightId, topology.edges);

    const flowNodes: Node[] = [];

    // Lane rails: span full vertical extent of the canvas, sized to the
    // bounding box of the nodes in that lane (plus padding).
    if (clusters.length > 0) {
      const totalYMin = clusters[0].yStart - LANE_HEADER;
      const totalYMax = clusters[clusters.length - 1].yEnd;
      const totalH = totalYMax - totalYMin + LANE_PAD;
      for (const lane of Object.keys(LANE_META) as Lane[]) {
        flowNodes.push({
          id: `lane-${lane}`,
          type: "lane",
          position: {
            x: LANE_X[lane] - NODE_HALF_W - LANE_PAD,
            y: totalYMin - LANE_PAD / 2,
          },
          data: { ...LANE_META[lane] },
          style: {
            width: NODE_HALF_W * 2 + LANE_PAD * 2,
            height: totalH,
          },
          selectable: false,
          draggable: false,
          zIndex: -2,
        });
      }
    }

    for (const n of visibleNodes) {
      const isHighlighted = !!highlight?.nodes.has(n.id);
      const isDimmed = !!highlight && !isHighlighted;
      flowNodes.push({
        id: n.id,
        type: n.type,
        position: positions[n.id] ?? { x: 0, y: 0 },
        data: {
          ...n,
          _dimmed: isDimmed,
          _highlighted: isHighlighted && n.id === highlightId,
        },
        zIndex: isHighlighted ? 2 : 1,
      });
    }

    const flowEdges: Edge[] = validEdges.map((e) => {
      const isHighlightedEdge = !!highlight?.edges.has(e.id);
      const isDimmedEdge = !!highlight && !isHighlightedEdge;
      // Visual flow: events → agents → external. The topology stores the
      // has_trigger edge as agent→trigger (ownership), but the data flow
      // is trigger→agent — swap endpoints so the arrow points the right way.
      const visualSource = e.relation === "has_trigger" ? e.target : e.source;
      const visualTarget = e.relation === "has_trigger" ? e.source : e.target;
      return {
        id: e.id,
        source: visualSource,
        target: visualTarget,
        type: "dataflow",
        data: {
          relation: e.relation,
          highlighted: isHighlightedEdge,
          dimmed: isDimmedEdge,
        },
        zIndex: isHighlightedEdge ? 2 : 0,
      };
    });

    return {
      nodes: flowNodes,
      edges: flowEdges,
      visibleCount: visibleNodes.length,
      clusterCount: clusters.length,
    };
  }, [topology, highlightId]);

  return (
    <div className="relative h-full w-full overflow-hidden bg-[#f8fafc] dark:bg-zinc-950">
      <div
        className="pointer-events-none absolute inset-0 opacity-80 dark:opacity-30"
        style={{
          backgroundImage:
            "linear-gradient(rgba(37,99,235,0.08) 1px, transparent 1px), linear-gradient(90deg, rgba(37,99,235,0.08) 1px, transparent 1px), radial-gradient(circle at 18% 12%, rgba(37,99,235,0.10), transparent 26%), radial-gradient(circle at 78% 22%, rgba(139,92,246,0.08), transparent 24%)",
          backgroundSize: "32px 32px, 32px 32px, auto, auto",
        }}
      />
      <div className="pointer-events-none absolute inset-x-0 top-0 z-10 flex justify-center px-4 pt-4">
        <div className="flex max-w-[520px] items-center gap-4 rounded-lg border border-blue-100/80 bg-white/85 px-4 py-2 shadow-[0_18px_60px_rgba(15,23,42,0.08)] backdrop-blur-xl dark:border-blue-900/40 dark:bg-zinc-950/80">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-blue-600 dark:text-blue-300">
              Agent Network
            </p>
            <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
              Governed data flow across boundaries
            </p>
          </div>
          <div className="h-8 w-px bg-zinc-200 dark:bg-zinc-800" />
          <div className="grid grid-cols-2 gap-3 text-right">
            <div>
              <p className="text-sm font-semibold leading-none text-zinc-950 dark:text-zinc-50">
                {visibleCount}
              </p>
              <p className="mt-0.5 text-[9px] uppercase tracking-[0.14em] text-zinc-400">
                Nodes
              </p>
            </div>
            <div>
              <p className="text-sm font-semibold leading-none text-zinc-950 dark:text-zinc-50">
                {clusterCount}
              </p>
              <p className="mt-0.5 text-[9px] uppercase tracking-[0.14em] text-zinc-400">
                Zones
              </p>
            </div>
          </div>
        </div>
      </div>
      <ReactFlow
        className="relative z-0 !bg-transparent"
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        nodesConnectable={false}
        elementsSelectable
        fitView
        fitViewOptions={{ padding: 0.18 }}
        minZoom={0.1}
        maxZoom={2}
        onPaneClick={onPaneClick}
        onNodeClick={(_, node) => {
          if (node.type === "lane") return;
          const networkNode = topology.nodes.find((n) => n.id === node.id);
          if (networkNode) onNodeClick?.(networkNode);
        }}
      >
        <Background
          variant={BackgroundVariant.Lines}
          gap={64}
          size={1}
          color="#dbeafe"
          className="opacity-70 dark:opacity-20"
        />
        <Controls className="!overflow-hidden !rounded-lg !border !border-blue-100 !bg-white/90 !shadow-[0_14px_40px_rgba(15,23,42,0.08)] !backdrop-blur dark:!border-blue-900/50 dark:!bg-zinc-950/85" />
      </ReactFlow>
    </div>
  );
}
