"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type cytoscape from "cytoscape";
import { Focus, LoaderCircle, Minus, Plus } from "lucide-react";
import type {
  NetworkEdgeData,
  NetworkNodeData,
  TopologyResponse,
} from "../types";

interface Props {
  topology: TopologyResponse;
  onNodeClick?: (node: NetworkNodeData) => void;
  highlightId?: string | null;
  onPaneClick?: () => void;
}

type FlowSide = "input" | "action";

interface FlowItem {
  edge: NetworkEdgeData;
  node: NetworkNodeData;
  source: string;
  target: string;
  side: FlowSide;
}

interface FlowSummary {
  inputCount: number;
  actionCount: number;
  hiddenInputCount: number;
  hiddenActionCount: number;
}

interface AgentFlowGraph {
  elements: cytoscape.ElementDefinition[];
  visibleNodes: NetworkNodeData[];
  summary: FlowSummary;
}

const INPUT_LIMIT = 5;
const ACTION_LIMIT = 7;
const COLUMN_X = { input: 100, agent: 560, action: 1020 } as const;
const ROW_GAP = 92;

function kindLabel(node: NetworkNodeData) {
  if (node.type === "agent") return "Agent";
  if (node.type === "trigger") {
    const triggerType = String(node.metadata.trigger_type ?? "trigger");
    return `${triggerType.charAt(0).toUpperCase()}${triggerType.slice(1)} trigger`;
  }
  if (node.type === "mcp_instance") return "MCP server";
  if (node.type === "openapi_connection") return "API connection";
  return "Skill";
}

function nodeDisplay(node: NetworkNodeData) {
  const status = node.status ? ` · ${node.status}` : "";
  return `${node.label}\n${kindLabel(node)}${status}`;
}

function relationLabel(relation: string) {
  if (relation === "has_trigger") return "starts";
  if (relation === "uses_mcp") return "queries";
  if (relation === "uses_openapi") return "calls";
  if (relation === "has_skill") return "applies";
  if (relation === "delegates_to") return "delegates";
  return "connects";
}

function edgeColor(relation: string) {
  if (relation === "has_trigger") return "#d97706";
  if (relation === "delegates_to") return "#6d5ce7";
  if (relation === "has_skill") return "#0891b2";
  return "#16836c";
}

function typeRank(node: NetworkNodeData) {
  const order: Record<NetworkNodeData["type"], number> = {
    trigger: 0,
    agent: 1,
    mcp_instance: 2,
    openapi_connection: 3,
    skill: 4,
  };
  return order[node.type];
}

function uniqueByNode(items: FlowItem[]) {
  const seen = new Set<string>();
  return items.filter((item) => {
    if (seen.has(item.node.id)) return false;
    seen.add(item.node.id);
    return true;
  });
}

function centerRows(count: number) {
  const start = -((count - 1) * ROW_GAP) / 2;
  return Array.from({ length: count }, (_, index) => start + index * ROW_GAP);
}

function collectFlowItems(
  topology: TopologyResponse,
  focusAgent: NetworkNodeData
) {
  const nodesById = new Map(topology.nodes.map((node) => [node.id, node]));
  const inputs: FlowItem[] = [];
  const actions: FlowItem[] = [];

  for (const edge of topology.edges) {
    if (edge.source !== focusAgent.id && edge.target !== focusAgent.id)
      continue;

    if (edge.relation === "has_trigger" && edge.source === focusAgent.id) {
      const node = nodesById.get(edge.target);
      if (node) {
        inputs.push({
          edge,
          node,
          source: node.id,
          target: focusAgent.id,
          side: "input",
        });
      }
      continue;
    }

    if (edge.source === focusAgent.id) {
      const node = nodesById.get(edge.target);
      if (node) {
        actions.push({
          edge,
          node,
          source: focusAgent.id,
          target: node.id,
          side: "action",
        });
      }
      continue;
    }

    const node = nodesById.get(edge.source);
    if (node) {
      inputs.push({
        edge,
        node,
        source: node.id,
        target: focusAgent.id,
        side: "input",
      });
    }
  }

  const sortItems = (a: FlowItem, b: FlowItem) =>
    typeRank(a.node) - typeRank(b.node) ||
    a.node.label.localeCompare(b.node.label);

  return {
    inputs: uniqueByNode(inputs.sort(sortItems)),
    actions: uniqueByNode(actions.sort(sortItems)),
  };
}

function entityElement(
  node: NetworkNodeData,
  x: number,
  y: number,
  classes = ""
): cytoscape.ElementDefinition {
  return {
    data: {
      id: node.id,
      display: nodeDisplay(node),
    },
    position: { x, y },
    classes: `entity entity-${node.type.replaceAll("_", "-")} ${classes}`,
  };
}

function summaryElement(
  id: string,
  display: string,
  x: number,
  y: number
): cytoscape.ElementDefinition {
  return {
    data: { id, display },
    position: { x, y },
    classes: "entity summary-node",
  };
}

function buildAgentFlow(
  topology: TopologyResponse,
  focusAgent: NetworkNodeData
): AgentFlowGraph {
  const { inputs, actions } = collectFlowItems(topology, focusAgent);
  const visibleInputs = inputs.slice(0, INPUT_LIMIT);
  const visibleActions = actions.slice(0, ACTION_LIMIT);
  const hiddenInputCount = inputs.length - visibleInputs.length;
  const hiddenActionCount = actions.length - visibleActions.length;
  const inputRows = centerRows(
    Math.max(1, visibleInputs.length + (hiddenInputCount > 0 ? 1 : 0))
  );
  const actionRows = centerRows(
    Math.max(1, visibleActions.length + (hiddenActionCount > 0 ? 1 : 0))
  );

  const elements: cytoscape.ElementDefinition[] = [
    entityElement(focusAgent, COLUMN_X.agent, 0, "focus-agent"),
  ];
  const visibleNodes = [focusAgent];
  const labelledRelations = new Set<string>();
  const edgeLabel = (item: FlowItem) => {
    const key = `${item.side}:${item.edge.relation}`;
    if (labelledRelations.has(key)) return "";
    labelledRelations.add(key);
    return relationLabel(item.edge.relation);
  };

  if (visibleInputs.length === 0) {
    elements.push(
      summaryElement(
        "empty:inputs",
        "No connected inputs\nRuns manually or by delegation",
        COLUMN_X.input,
        inputRows[0]
      )
    );
  }

  visibleInputs.forEach((item, index) => {
    elements.push(entityElement(item.node, COLUMN_X.input, inputRows[index]));
    visibleNodes.push(item.node);
    elements.push({
      data: {
        id: `route:${item.edge.id}`,
        source: item.source,
        target: item.target,
        relationLabel: edgeLabel(item),
        edgeColor: edgeColor(item.edge.relation),
      },
      classes: `route route-${item.edge.relation.replaceAll("_", "-")}`,
    });
  });

  if (hiddenInputCount > 0) {
    const id = "summary:inputs";
    const y = inputRows[inputRows.length - 1];
    elements.push(
      summaryElement(
        id,
        `+ ${hiddenInputCount} more inputs\nGrouped to keep this path readable`,
        COLUMN_X.input,
        y
      ),
      {
        data: {
          id: "route:summary-inputs",
          source: id,
          target: focusAgent.id,
          relationLabel: "also start",
          edgeColor: "#d97706",
        },
        classes: "route route-summary",
      }
    );
  }

  if (visibleActions.length === 0) {
    elements.push(
      summaryElement(
        "empty:actions",
        "No connected actions\nNo tools, skills, or delegates",
        COLUMN_X.action,
        actionRows[0]
      )
    );
  }

  visibleActions.forEach((item, index) => {
    elements.push(entityElement(item.node, COLUMN_X.action, actionRows[index]));
    visibleNodes.push(item.node);
    elements.push({
      data: {
        id: `route:${item.edge.id}`,
        source: item.source,
        target: item.target,
        relationLabel: edgeLabel(item),
        edgeColor: edgeColor(item.edge.relation),
      },
      classes: `route route-${item.edge.relation.replaceAll("_", "-")}`,
    });
  });

  if (hiddenActionCount > 0) {
    const id = "summary:actions";
    const y = actionRows[actionRows.length - 1];
    elements.push(
      summaryElement(
        id,
        `+ ${hiddenActionCount} more actions\nGrouped to keep this path readable`,
        COLUMN_X.action,
        y
      ),
      {
        data: {
          id: "route:summary-actions",
          source: focusAgent.id,
          target: id,
          relationLabel: "also uses",
          edgeColor: "#16836c",
        },
        classes: "route route-summary",
      }
    );
  }

  return {
    elements,
    visibleNodes,
    summary: {
      inputCount: inputs.length,
      actionCount: actions.length,
      hiddenInputCount,
      hiddenActionCount,
    },
  };
}

function chooseDefaultAgent(topology: TopologyResponse) {
  const agents = topology.nodes.filter((node) => node.type === "agent");
  if (agents.length === 0) return null;

  const degree = new Map(agents.map((agent) => [agent.id, 0]));
  for (const edge of topology.edges) {
    if (degree.has(edge.source)) {
      degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
    }
    if (degree.has(edge.target)) {
      degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
    }
  }

  return [...agents].sort(
    (a, b) =>
      (degree.get(b.id) ?? 0) - (degree.get(a.id) ?? 0) ||
      a.label.localeCompare(b.label)
  )[0].id;
}

function topologyStyles(dark: boolean): cytoscape.StylesheetJson {
  const canvas = dark ? "#09090b" : "#f7f9fc";
  const nodeFill = dark ? "#18181b" : "#ffffff";
  const nodeText = dark ? "#f4f4f5" : "#172033";
  const quietText = dark ? "#a1a1aa" : "#64748b";

  const styles = [
    {
      selector: "core",
      style: {
        "selection-box-color": "#4f67e8",
        "selection-box-opacity": 0.08,
        "selection-box-border-color": "#4f67e8",
        "active-bg-opacity": 0,
        "outside-texture-bg-color": canvas,
        "outside-texture-bg-opacity": 1,
      },
    },
    {
      selector: "node.entity",
      style: {
        width: 236,
        height: 66,
        shape: "roundrectangle",
        "background-color": nodeFill,
        "background-opacity": 1,
        "border-width": 2,
        "border-color": "#94a3b8",
        label: "data(display)",
        color: nodeText,
        "font-family": "Inter, ui-sans-serif, system-ui, sans-serif",
        "font-size": 12,
        "font-weight": 600,
        "text-valign": "center",
        "text-halign": "center",
        "text-justification": "left",
        "text-margin-x": 0,
        "text-wrap": "wrap",
        "text-max-width": 198,
        "min-zoomed-font-size": 9,
        "overlay-opacity": 0,
        "transition-property": "opacity, border-width, background-color",
        "transition-duration": "140ms",
        "z-index": 10,
      },
    },
    {
      selector: "node.entity-trigger",
      style: { "border-color": "#d97706" },
    },
    {
      selector: "node.entity-agent",
      style: { "border-color": "#5b6ff0" },
    },
    {
      selector: "node.entity-mcp-instance",
      style: { "border-color": "#16836c" },
    },
    {
      selector: "node.entity-openapi-connection",
      style: { "border-color": "#16836c" },
    },
    {
      selector: "node.entity-skill",
      style: { "border-color": "#0891b2" },
    },
    {
      selector: "node.focus-agent",
      style: {
        width: 278,
        height: 92,
        "border-width": 4,
        "border-color": "#4f67e8",
        "background-color": dark ? "#20264b" : "#ffffff",
        "font-size": 14,
        "font-weight": 700,
        "text-max-width": 230,
      },
    },
    {
      selector: "node.summary-node",
      style: {
        "border-width": 1,
        "border-style": "dashed",
        "border-color": dark ? "#52525b" : "#94a3b8",
        "background-color": dark ? "#18181b" : "#f8fafc",
        color: quietText,
        "font-weight": 500,
      },
    },
    {
      selector: "edge.route",
      style: {
        width: 2,
        opacity: 0.9,
        "line-color": "data(edgeColor)",
        "target-arrow-color": "data(edgeColor)",
        "target-arrow-shape": "triangle",
        "arrow-scale": 0.86,
        "curve-style": "taxi",
        "taxi-direction": "rightward",
        "taxi-turn": "50%",
        "taxi-turn-min-distance": 32,
        "line-cap": "round",
        label: "data(relationLabel)",
        color: quietText,
        "font-family": "ui-monospace, SFMono-Regular, Menlo, monospace",
        "font-size": 10,
        "font-weight": 600,
        "text-background-color": canvas,
        "text-background-opacity": 0.94,
        "text-background-padding": 4,
        "text-rotation": "autorotate",
        "overlay-opacity": 0,
        "transition-property": "opacity, width",
        "transition-duration": "140ms",
        "z-index": 4,
      },
    },
    {
      selector: "edge.route-has-skill, edge.route-summary",
      style: { "line-style": "dashed" },
    },
    {
      selector: ".is-dimmed",
      style: { opacity: 0.12 },
    },
    {
      selector: "node.is-selected",
      style: { "border-width": 5 },
    },
    {
      selector: "node.is-hovered",
      style: { "border-width": 4 },
    },
  ];

  // Cytoscape supports taxi routing properties at runtime that are not
  // represented completely in its bundled TypeScript types.
  return styles as unknown as cytoscape.StylesheetJson;
}

export default function CytoscapeTopologyView({
  topology,
  onNodeClick,
  highlightId,
  onPaneClick,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<cytoscape.Core | null>(null);
  const onNodeClickRef = useRef(onNodeClick);
  const onPaneClickRef = useRef(onPaneClick);
  const agents = useMemo(
    () =>
      topology.nodes
        .filter((node) => node.type === "agent")
        .sort((a, b) => a.label.localeCompare(b.label)),
    [topology]
  );
  const defaultAgentId = useMemo(
    () => chooseDefaultAgent(topology),
    [topology]
  );
  const [focusAgentId, setFocusAgentId] = useState<string | null>(
    defaultAgentId
  );
  const [layoutPending, setLayoutPending] = useState(true);

  useEffect(() => {
    onNodeClickRef.current = onNodeClick;
    onPaneClickRef.current = onPaneClick;
  }, [onNodeClick, onPaneClick]);

  useEffect(() => {
    if (!agents.some((agent) => agent.id === focusAgentId)) {
      setFocusAgentId(defaultAgentId);
    }
  }, [agents, defaultAgentId, focusAgentId]);

  const focusAgent = agents.find((agent) => agent.id === focusAgentId) ?? null;
  const flow = useMemo(
    () => (focusAgent ? buildAgentFlow(topology, focusAgent) : null),
    [focusAgent, topology]
  );

  useEffect(() => {
    const target = containerRef.current;
    if (!target || !flow) return;
    const targetElement: HTMLDivElement = target;
    const flowGraph = flow;
    let disposed = false;
    let resizeObserver: ResizeObserver | null = null;
    let themeObserver: MutationObserver | null = null;
    let resizeFrame: number | null = null;
    let readyFrame: number | null = null;
    const nodesById = new Map(
      flowGraph.visibleNodes.map((node) => [node.id, node])
    );

    async function mount() {
      const { default: cytoscape } = await import("cytoscape");
      if (disposed) return;

      const isDark = () => document.documentElement.classList.contains("dark");
      const cy = cytoscape({
        container: targetElement,
        elements: flowGraph.elements,
        style: topologyStyles(isDark()),
        layout: {
          name: "preset",
          fit: true,
          padding: 74,
        },
        minZoom: 0.38,
        maxZoom: 2.2,
        boxSelectionEnabled: false,
        autoungrabify: true,
        autounselectify: true,
        pixelRatio: "auto",
      });
      cyRef.current = cy;

      cy.on("tap", "node.entity", (event) => {
        const node = nodesById.get(event.target.id());
        if (node) onNodeClickRef.current?.(node);
      });
      cy.on("mouseover", "node.entity", (event) => {
        if (nodesById.has(event.target.id())) {
          event.target.addClass("is-hovered");
        }
      });
      cy.on("mouseout", "node.entity", (event) => {
        event.target.removeClass("is-hovered");
      });
      cy.on("tap", (event) => {
        if (event.target === cy) onPaneClickRef.current?.();
      });

      resizeObserver = new ResizeObserver(() => {
        if (resizeFrame !== null) window.cancelAnimationFrame(resizeFrame);
        resizeFrame = window.requestAnimationFrame(() => {
          cy.resize();
          cy.fit(cy.elements(), 74);
        });
      });
      resizeObserver.observe(targetElement);
      themeObserver = new MutationObserver(() => {
        cy.style().fromJson(topologyStyles(isDark())).update();
      });
      themeObserver.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ["class"],
      });

      readyFrame = window.requestAnimationFrame(() => {
        cy.fit(cy.elements(), 74);
        if (!disposed) setLayoutPending(false);
      });
    }

    setLayoutPending(true);
    void mount();

    return () => {
      disposed = true;
      resizeObserver?.disconnect();
      themeObserver?.disconnect();
      if (resizeFrame !== null) window.cancelAnimationFrame(resizeFrame);
      if (readyFrame !== null) window.cancelAnimationFrame(readyFrame);
      cyRef.current?.destroy();
      cyRef.current = null;
    };
  }, [flow]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.elements().removeClass("is-dimmed is-near is-selected");
    if (!highlightId) return;

    const selected = cy.getElementById(highlightId);
    if (selected.empty()) return;
    const near = selected.closedNeighborhood();
    cy.nodes(".entity").difference(near.nodes(".entity")).addClass("is-dimmed");
    cy.edges(".route").difference(near.edges(".route")).addClass("is-dimmed");
    near.addClass("is-near");
    selected.addClass("is-selected");
  }, [flow, highlightId, layoutPending]);

  const zoomBy = (factor: number) => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.animate({
      zoom: Math.max(cy.minZoom(), Math.min(cy.maxZoom(), cy.zoom() * factor)),
      duration: 140,
    });
  };

  if (!focusAgent || !flow) {
    return (
      <div className="flex h-full items-center justify-center bg-[#f7f9fc] px-6 text-center dark:bg-zinc-950">
        <div>
          <p className="text-sm font-semibold">No agents to map</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Create an agent first; its inputs and actions will appear here.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="relative h-full w-full overflow-hidden bg-[#f7f9fc] dark:bg-zinc-950">
      <div className="absolute inset-x-0 top-0 z-10 flex h-[72px] items-center justify-between gap-4 border-b border-slate-200/80 bg-white/95 px-4 backdrop-blur dark:border-zinc-800 dark:bg-zinc-950/95 md:px-5">
        <div className="flex min-w-0 items-center gap-3">
          <div className="shrink-0">
            <p className="font-mono text-[9px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
              Execution path
            </p>
            <label htmlFor="topology-agent" className="sr-only">
              Agent to inspect
            </label>
            <select
              id="topology-agent"
              value={focusAgent.id}
              onChange={(event) => {
                onPaneClick?.();
                setFocusAgentId(event.target.value);
              }}
              className="mt-0.5 max-w-[290px] cursor-pointer rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-sm font-semibold text-foreground outline-none focus-visible:ring-2 focus-visible:ring-primary dark:border-zinc-700 dark:bg-zinc-900 md:max-w-[420px] md:text-base"
            >
              {agents.map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.label}
                </option>
              ))}
            </select>
          </div>
          <div className="hidden h-8 w-px bg-border sm:block" />
          <p className="hidden max-w-md text-xs leading-5 text-muted-foreground sm:block">
            What starts this agent, what it decides, and which systems it can
            call. Only direct connections are shown.
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2 font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
          <span className="rounded-full border border-amber-200 bg-amber-50 px-2 py-1 text-amber-700 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300">
            {flow.summary.inputCount} inputs
          </span>
          <span aria-hidden="true">→</span>
          <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2 py-1 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300">
            {flow.summary.actionCount} actions
          </span>
        </div>
      </div>

      <div
        className="pointer-events-none absolute inset-x-0 bottom-0 top-[72px] opacity-70 dark:opacity-20"
        style={{
          backgroundImage:
            "radial-gradient(circle, rgba(100,116,139,0.18) 1px, transparent 1px)",
          backgroundSize: "22px 22px",
        }}
      />
      <div className="pointer-events-none absolute inset-x-5 bottom-5 top-[92px] grid grid-cols-[1fr_0.82fr_1fr] gap-4">
        <section className="rounded-2xl border border-amber-300/80 bg-amber-50/55 p-4 dark:border-amber-900/80 dark:bg-amber-950/20">
          <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-amber-700 dark:text-amber-300">
            1 · Inputs
          </p>
          <p className="mt-1 text-[11px] text-amber-800/70 dark:text-amber-200/60">
            {flow.summary.inputCount} direct sources start this agent
          </p>
        </section>
        <section className="rounded-2xl border border-indigo-300/80 bg-indigo-50/60 p-4 dark:border-indigo-900/80 dark:bg-indigo-950/20">
          <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-indigo-700 dark:text-indigo-300">
            2 · Agent
          </p>
          <p className="mt-1 text-[11px] text-indigo-800/70 dark:text-indigo-200/60">
            Receives context, decides, and routes work
          </p>
        </section>
        <section className="rounded-2xl border border-emerald-300/80 bg-emerald-50/55 p-4 dark:border-emerald-900/80 dark:bg-emerald-950/20">
          <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-emerald-700 dark:text-emerald-300">
            3 · Actions
          </p>
          <p className="mt-1 text-[11px] text-emerald-800/70 dark:text-emerald-200/60">
            {flow.summary.actionCount} tools, skills, or delegated agents
          </p>
        </section>
      </div>
      <div
        ref={containerRef}
        className="absolute inset-x-0 bottom-0 top-[72px] z-[1]"
        role="application"
        aria-label={`Execution topology for ${focusAgent.label}`}
      />

      {layoutPending && (
        <div className="pointer-events-none absolute inset-x-0 bottom-0 top-[72px] z-10 flex items-center justify-center bg-[#f7f9fc]/75 backdrop-blur-[2px] dark:bg-zinc-950/75">
          <div className="flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.14em] text-slate-500 shadow-sm dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400">
            <LoaderCircle className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" />
            Building execution path
          </div>
        </div>
      )}

      <div className="absolute bottom-3 left-3 z-10 flex overflow-hidden rounded-lg border border-slate-200 bg-white/95 shadow-sm backdrop-blur dark:border-zinc-800 dark:bg-zinc-950/95">
        <button
          type="button"
          onClick={() => zoomBy(1.2)}
          className="flex h-8 w-8 items-center justify-center text-slate-600 transition-colors hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary dark:text-zinc-300 dark:hover:bg-zinc-800"
          aria-label="Zoom in"
        >
          <Plus className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={() => zoomBy(0.84)}
          className="flex h-8 w-8 items-center justify-center border-l border-slate-200 text-slate-600 transition-colors hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-800"
          aria-label="Zoom out"
        >
          <Minus className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={() => cyRef.current?.fit(cyRef.current.elements(), 74)}
          className="flex h-8 w-8 items-center justify-center border-l border-slate-200 text-slate-600 transition-colors hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-800"
          aria-label="Fit execution path"
        >
          <Focus className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}
