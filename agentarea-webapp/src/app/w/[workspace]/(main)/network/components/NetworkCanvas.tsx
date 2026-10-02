"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import type {
  Core,
  ElementDefinition,
  LayoutOptions,
  NodeSingular,
  StylesheetJson,
} from "cytoscape";
import { Focus, Minus, Plus } from "lucide-react";
import { ENTITY_ICONS, type EntityKind } from "@/lib/entity-icons";
import { BRAND_MARKS } from "@/lib/entity-identity";
import type { NetworkNodeData } from "../types";
import { hierarchyPositions, shelfPositions } from "../utils/hierarchyLayout";
import { getNodeIdentity } from "../utils/networkConnections";
import {
  isolatedNodes,
  isResource,
  type GraphKind,
  type GraphLens,
  type NetworkGraph,
} from "../utils/networkGraph";

const KINDS: Record<GraphKind, EntityKind> = {
  agent: "agent",
  mcp_instance: "mcp",
  openapi_connection: "client",
  skill: "skill",
  trigger: "trigger",
  person: "person",
};

// Each role is read off a Tailwind class so the canvas follows the theme the
// rest of the page is drawn in, light or dark, without a second palette.
const PALETTE = {
  primary: "text-primary",
  foreground: "text-foreground",
  muted: "text-muted-foreground",
  border: "text-border",
  background: "text-background",
  destructive: "text-destructive",
  internal: "text-emerald-600 dark:text-emerald-400",
  external: "text-amber-600 dark:text-amber-400",
  trigger: "text-violet-600 dark:text-violet-400",
  person: "text-slate-500 dark:text-slate-400",
  match: "text-amber-500",
} as const;
type Palette = Record<keyof typeof PALETTE, string>;

const ISOLATED_GROUP = "__network_isolated__";

const controlClass =
  "flex h-9 w-9 items-center justify-center text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary";

export interface NetworkCanvasProps {
  graph: NetworkGraph;
  nodes: NetworkNodeData[];
  lens: GraphLens;
  selectedId: string | null;
  path: { nodes: Set<string>; edges: Set<string> } | null;
  matches: Set<string>;
  showIssues: boolean;
  ariaLabel: string;
  onSelectNode: (id: string) => void;
  onSelectEdge: (id: string) => void;
  onClear: () => void;
}

function nodeSize(kind: GraphKind, degree: number) {
  if (kind === "agent") return 38 + Math.min(28, degree * 4);
  if (kind === "trigger") return 28;
  if (kind === "person") return 26;
  return 30 + Math.min(16, degree * 3);
}

function svgUri(markup: string, color: string) {
  return (
    "data:image/svg+xml;utf8," +
    encodeURIComponent(markup.replaceAll("currentColor", color))
  );
}

/**
 * The first logo that loads for each connection. EntityMark walks the same
 * chain with `<img onError>`; a canvas has no element to fail, so the chain is
 * walked here and only a URL that is known to load reaches the graph.
 */
function useLogos(nodes: NetworkNodeData[]) {
  const [logos, setLogos] = useState<Map<string, string>>(new Map());
  const key = nodes
    .filter((node) => isResource(node.type))
    .map((node) => node.id)
    .join("|");
  useEffect(() => {
    let cancelled = false;
    const load = (src: string) =>
      new Promise<boolean>((resolve) => {
        const image = new Image();
        image.onload = () => resolve(image.naturalWidth > 0);
        image.onerror = () => resolve(false);
        image.src = src;
      });
    for (const node of nodes) {
      if (!isResource(node.type)) continue;
      const identity = getNodeIdentity(node);
      const brand = BRAND_MARKS[identity.kind];
      const sources = brand ? [...identity.sources, brand] : identity.sources;
      void (async () => {
        for (const src of sources) {
          if (await load(src)) {
            if (!cancelled)
              setLogos((current) => new Map(current).set(node.id, src));
            return;
          }
        }
      })();
    }
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed by node ids
  }, [key]);
  return logos;
}

function stylesheet(
  palette: Palette,
  glyphs: Partial<Record<EntityKind, string>>,
  logos: Map<string, string>,
  font: string,
  transition: number
): StylesheetJson {
  const glyph = (kind: GraphKind, color: string) => {
    const markup = glyphs[KINDS[kind]];
    return markup ? svgUri(markup, color) : "none";
  };
  const scopeColor = (scope: string | null) =>
    scope === "egress"
      ? palette.external
      : scope === "private"
        ? palette.internal
        : palette.muted;
  const image = (node: NodeSingular) => {
    const kind = node.data("kind") as GraphKind;
    if (kind === "agent" || kind === "person") return glyph(kind, "#ffffff");
    if (kind === "trigger")
      return glyph(kind, node.data("off") ? palette.muted : palette.trigger);
    return logos.get(node.id()) ?? glyph(kind, scopeColor(node.data("scope")));
  };

  return [
    {
      selector: "node[size]",
      style: { width: "data(size)", height: "data(size)" },
    },
    {
      selector: "node",
      style: {
        "background-color": palette.background,
        "background-image": image,
        // Logos come from customer hosts that send no CORS headers; "null"
        // loads them as plain images. The typings omit this valid value.
        "background-image-crossorigin": "null" as unknown as "anonymous",
        "background-width": "52%",
        "background-height": "52%",
        "border-width": 2,
        "border-color": palette.border,
        label: "data(label)",
        "font-family": font,
        "font-size": 11,
        "font-weight": 500,
        color: palette.foreground,
        "text-valign": "bottom",
        "text-margin-y": 5,
        "text-background-color": palette.background,
        "text-background-opacity": 0.85,
        "text-background-padding": "2px",
        "text-background-shape": "roundrectangle",
        "text-wrap": "ellipsis",
        "text-max-width": "140px",
        "min-zoomed-font-size": 9,
        "transition-property":
          "opacity, border-width, border-color, background-color, underlay-opacity",
        "transition-duration": transition,
      },
    },
    {
      selector: "node[kind = 'agent']",
      style: {
        "background-color": palette.primary,
        "border-color": palette.background,
        "border-width": 3,
        "font-size": 12,
        "font-weight": 600,
        "text-max-width": "180px",
      },
    },
    {
      selector: "node[kind = 'agent'][?off]",
      style: { "background-color": palette.muted },
    },
    {
      selector:
        "node[kind = 'mcp_instance'], node[kind = 'openapi_connection'], node[kind = 'skill']",
      style: {
        "border-width": 2.5,
        "border-color": (node: NodeSingular) => scopeColor(node.data("scope")),
      },
    },
    { selector: "node[kind = 'skill']", style: { shape: "round-rectangle" } },
    {
      selector: "node[?failed]",
      style: { "border-color": palette.destructive },
    },
    {
      selector: "node[kind = 'trigger']",
      style: {
        shape: "round-diamond",
        "border-color": palette.trigger,
        "font-size": 10,
        color: palette.muted,
      },
    },
    {
      selector: "node[kind = 'trigger'][?off]",
      style: { "border-color": palette.muted, "border-style": "dashed" },
    },
    {
      selector: "node[kind = 'person']",
      style: {
        "background-color": palette.person,
        "border-color": palette.background,
        "font-size": 10,
        color: palette.muted,
      },
    },
    {
      selector: "edge",
      style: {
        width: 1.5,
        "curve-style": "bezier",
        "line-color": palette.muted,
        "target-arrow-color": palette.muted,
        "target-arrow-shape": "triangle",
        "arrow-scale": 0.8,
        opacity: 0.55,
        "font-family": font,
        "font-size": 10,
        color: palette.muted,
        "text-background-color": palette.background,
        "text-background-opacity": 1,
        "text-background-padding": "2px",
        "text-rotation": "autorotate",
        "min-zoomed-font-size": 8,
        "transition-property": "opacity, width, line-color, target-arrow-color",
        "transition-duration": transition,
      },
    },
    {
      selector: "edge[relation = 'delegates_to']",
      style: {
        width: 2,
        "line-color": palette.primary,
        "target-arrow-color": palette.primary,
      },
    },
    {
      selector:
        "edge[relation = 'uses_mcp'], edge[relation = 'uses_openapi'], edge[relation = 'has_skill']",
      style: { "line-style": "dashed", "line-dash-pattern": [5, 4] },
    },
    {
      selector: "edge[relation = 'has_trigger'], edge[relation = 'member_of']",
      style: {
        "line-style": "dotted",
        "line-color": palette.trigger,
        "target-arrow-color": palette.trigger,
      },
    },
    {
      selector: "edge[relation = 'has_trigger'][?off]",
      style: {
        "line-color": palette.muted,
        "target-arrow-color": palette.muted,
        opacity: 0.35,
      },
    },
    {
      selector: "edge[relation = 'person_access']",
      style: {
        width: 1,
        "line-color": palette.person,
        "target-arrow-color": palette.person,
        opacity: 0.4,
      },
    },
    {
      selector: "edge[relation = 'person_access'][?off]",
      style: {
        "line-color": palette.destructive,
        "target-arrow-color": palette.destructive,
        "target-arrow-shape": "tee",
        "line-style": "dashed",
        opacity: 0.85,
      },
    },
    {
      selector: "node[kind = 'group']",
      style: {
        shape: "round-rectangle",
        "background-color": palette.muted,
        "background-opacity": 0.04,
        "background-image": "none",
        "border-width": 1,
        "border-style": "dashed",
        "border-color": palette.border,
        padding: "24px",
        "text-valign": "top",
        "text-halign": "center",
        "text-margin-y": -6,
        "text-background-opacity": 0,
        "font-size": 11,
        color: palette.muted,
      },
    },
    { selector: ".faded", style: { opacity: 0.1 } },
    {
      selector: "edge.lit",
      style: { opacity: 1, width: 2.4, label: "data(label)", "z-index": 10 },
    },
    {
      selector: "node.focus",
      style: { "border-width": 4, "border-color": palette.foreground },
    },
    {
      selector: "edge.focus",
      style: { width: 3, opacity: 1, label: "data(label)", "z-index": 11 },
    },
    {
      selector: "node.match",
      style: { "border-width": 4, "border-color": palette.match },
    },
    {
      selector: "node.issue",
      style: {
        "underlay-color": palette.destructive,
        "underlay-opacity": 0.18,
        "underlay-padding": 7,
        "underlay-shape": "ellipse",
        "border-color": palette.destructive,
      },
    },
  ];
}

const MOTION_MS = 450;

/**
 * Bring the canvas to `elements` by difference: keep what stays, so it can
 * move to its new place, add what is new beside a neighbour that already
 * exists, and drop what is gone. Rebuilding everything made each change
 * redraw the graph from nothing.
 */
function syncElements(cy: Core, elements: ElementDefinition[]) {
  const next = new Map(elements.map((element) => [element.data.id, element]));
  const centre = (() => {
    const extent = cy.extent();
    return { x: (extent.x1 + extent.x2) / 2, y: (extent.y1 + extent.y2) / 2 };
  })();
  cy.batch(() => {
    for (const element of elements) {
      const id = element.data.id as string;
      const existing = cy.getElementById(id);
      const { id: _id, parent, source: _s, target: _t, ...data } = element.data;
      if (existing.nonempty()) {
        existing.data(data);
        if (
          existing.group() === "nodes" &&
          (existing.data("parent") ?? null) !== (parent ?? null)
        ) {
          existing.nodes().move({ parent: parent ?? null });
        }
        continue;
      }
      if (element.group === "edges") {
        cy.add(element);
        continue;
      }
      const neighbour = elements.find(
        (other) =>
          other.group === "edges" &&
          (other.data.source === id || other.data.target === id) &&
          cy
            .getElementById(
              other.data.source === id ? other.data.target : other.data.source
            )
            .nonempty()
      );
      const anchor = neighbour
        ? cy
            .getElementById(
              neighbour.data.source === id
                ? neighbour.data.target
                : neighbour.data.source
            )
            .position()
        : centre;
      cy.add({ ...element, position: { ...anchor } });
    }
    cy.elements()
      .filter((element) => !next.has(element.id()))
      .remove();
  });
}

export default function NetworkCanvas({
  graph,
  nodes,
  lens,
  selectedId,
  path,
  matches,
  showIssues,
  ariaLabel,
  onSelectNode,
  onSelectEdge,
  onClear,
}: NetworkCanvasProps) {
  const t = useTranslations("NetworkPage.graph");
  const relations = useTranslations("NetworkPage.orgChart");
  const container = useRef<HTMLDivElement>(null);
  const sprite = useRef<HTMLDivElement>(null);
  const probes = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const [ready, setReady] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [theme, setTheme] = useState(0);
  const logos = useLogos(nodes);
  const handlers = useRef({ onSelectNode, onSelectEdge, onClear });
  handlers.current = { onSelectNode, onSelectEdge, onClear };
  const selection = useRef(selectedId);
  selection.current = selectedId ?? (path ? "path" : null);

  useEffect(() => {
    const observer = new MutationObserver(() => setTheme((value) => value + 1));
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class"],
    });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    let disposed = false;
    let cy: Core | null = null;
    void Promise.all([import("cytoscape"), import("cytoscape-fcose")]).then(
      ([{ default: cytoscape }, { default: fcose }]) => {
        if (disposed || !container.current) return;
        cytoscape.use(fcose);
        cy = cytoscape({
          container: container.current,
          minZoom: 0.1,
          maxZoom: 2.5,
          wheelSensitivity: 0.25,
          boxSelectionEnabled: false,
          autoungrabify: false,
        });
        cy.on("tap", "node", (event) =>
          event.target.id() === ISOLATED_GROUP
            ? handlers.current.onClear()
            : handlers.current.onSelectNode(event.target.id())
        );
        cy.on("tap", "edge", (event) =>
          handlers.current.onSelectEdge(event.target.id())
        );
        cy.on("tap", (event) => {
          if (event.target === cy) handlers.current.onClear();
        });
        cy.on("mouseover", "node", (event) => {
          if (selection.current || !cy) return;
          if (event.target.id() === ISOLATED_GROUP) return;
          const hood = event.target.closedNeighborhood();
          cy.elements().not(hood).addClass("faded");
          hood.edges().addClass("lit");
        });
        cy.on("mouseout", "node", () => {
          if (selection.current || !cy) return;
          cy.elements().removeClass("faded lit");
        });
        cy.on("zoom", () => cy && setZoom(cy.zoom()));
        cyRef.current = cy;
        setReady(true);
      }
    );
    const observer = new ResizeObserver(() => cyRef.current?.resize());
    if (container.current) observer.observe(container.current);
    return () => {
      disposed = true;
      observer.disconnect();
      cy?.destroy();
      cyRef.current = null;
    };
  }, []);

  const elements = useMemo<ElementDefinition[]>(() => {
    const isolated = new Set(isolatedNodes(graph).map((node) => node.id));
    const framed = isolated.size > 0 && isolated.size < graph.nodes.length;
    return [
      ...(framed
        ? [
            {
              group: "nodes" as const,
              data: {
                id: ISOLATED_GROUP,
                kind: "group",
                label: t("isolated", { count: isolated.size }),
              },
            },
          ]
        : []),
      ...graph.nodes.map((node) => ({
        group: "nodes" as const,
        data: {
          id: node.id,
          parent: framed && isolated.has(node.id) ? ISOLATED_GROUP : undefined,
          isolated: isolated.has(node.id),
          label: node.label,
          kind: node.kind,
          scope: node.scope,
          off: node.off,
          failed: node.failed,
          size: nodeSize(node.kind, node.degree),
          issues: node.issues.length,
        },
      })),
      ...graph.edges.map((edge) => ({
        group: "edges" as const,
        data: {
          id: edge.id,
          source: edge.source,
          target: edge.target,
          relation: edge.relation,
          off: edge.off,
          label:
            edge.relation === "person_access"
              ? t(edge.off ? "denied" : "allowed")
              : relations.has(`relations.${edge.relation}`)
                ? relations(`relations.${edge.relation}`)
                : edge.relation,
        },
      })),
    ];
  }, [graph, t, relations]);
  const structure = `${lens}#${elements.map((element) => element.data.id).join("|")}`;

  useEffect(() => {
    const cy = cyRef.current;
    if (!ready || !cy || !sprite.current || !probes.current) return;
    const glyphs: Partial<Record<EntityKind, string>> = {};
    sprite.current.querySelectorAll("svg").forEach((svg) => {
      const kind = svg.getAttribute("data-kind") as EntityKind;
      svg.setAttribute("xmlns", "http://www.w3.org/2000/svg");
      glyphs[kind] = svg.outerHTML;
    });
    const palette = {} as Palette;
    probes.current.querySelectorAll("span").forEach((probe) => {
      palette[probe.dataset.role as keyof Palette] =
        getComputedStyle(probe).color;
    });
    cy.style(
      stylesheet(
        palette,
        glyphs,
        logos,
        getComputedStyle(container.current ?? document.body).fontFamily,
        window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 160
      )
    );
  }, [ready, logos, theme]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!ready || !cy) return;
    syncElements(cy, elements);
    const duration = window.matchMedia("(prefers-reduced-motion: reduce)")
      .matches
      ? 0
      : MOTION_MS;
    const order = isolatedNodes(graph).map((node) => node.id);
    const group = cy.getElementById(ISOLATED_GROUP);
    const isolated = cy
      .nodes("[?isolated]")
      .sort((a, b) => order.indexOf(a.id()) - order.indexOf(b.id()));
    const connected = cy.elements().not(isolated).not(group);
    const movable = cy.nodes("[kind != 'group']");
    const before = new Map(
      movable.map((node) => [node.id(), { ...node.position() }])
    );

    // Settle the final layout instantly, then play one transition from where
    // every node was to where it lands, camera included — so switching lens
    // or adding a node moves the graph instead of rebuilding it.
    if (connected.nonempty()) {
      if (lens === "overview") {
        // fcose starts from random positions; a fixed seed keeps the same
        // workspace looking the same between visits.
        const random = Math.random;
        let seed = 7;
        Math.random = () => {
          seed = (seed * 16807) % 2147483647;
          return (seed - 1) / 2147483646;
        };
        try {
          connected
            .layout({
              name: "fcose",
              quality: "proof",
              randomize: true,
              animate: false,
              nodeDimensionsIncludeLabels: true,
              nodeRepulsion: () => 9000,
              idealEdgeLength: (edge: { data: (key: string) => string }) =>
                edge.data("relation") === "delegates_to" ? 90 : 120,
              nodeSeparation: 80,
              packComponents: true,
              tilingPaddingVertical: 40,
              tilingPaddingHorizontal: 60,
              fit: false,
            } as LayoutOptions)
            .run();
        } finally {
          Math.random = random;
        }
      } else {
        const positions = hierarchyPositions(
          connected.nodes().map((node) => ({
            id: node.id(),
            size: node.data("size") as number,
          })),
          connected.edges().map((edge) => ({
            source: edge.source().id(),
            target: edge.target().id(),
          })),
          lens === "delegation" ? "TB" : "LR"
        );
        connected
          .nodes()
          .positions((node) => positions.get(node.id()) ?? { x: 0, y: 0 });
      }
    }
    if (isolated.nonempty()) {
      const ids = isolated.map((node) => node.id());
      let positions;
      if (connected.empty()) {
        positions = shelfPositions(ids, { x: 0, y: 0 }, cy.width());
      } else {
        const box = connected.boundingBox();
        // Beside the graph when it is narrower than the screen, below it
        // otherwise, so the shelf spends the room the graph leaves free.
        const beside = box.w / Math.max(box.h, 1) < cy.width() / cy.height();
        positions = beside
          ? shelfPositions(
              ids,
              { x: box.x2 + 100, y: box.y1 },
              Math.max(300, box.h * (cy.width() / cy.height()) - box.w - 100)
            )
          : shelfPositions(
              ids,
              { x: box.x1, y: box.y2 + 100 },
              Math.max(box.w, 450)
            );
      }
      isolated.positions((node) => positions.get(node.id()) ?? { x: 0, y: 0 });
    }

    const after = new Map(
      movable.map((node) => [node.id(), { ...node.position() }])
    );
    const box = cy.elements().boundingBox();
    const padding = 40;
    const zoom = Math.min(
      cy.maxZoom(),
      Math.max(
        cy.minZoom(),
        Math.min(
          (cy.width() - 2 * padding) / Math.max(box.w, 1),
          (cy.height() - 2 * padding) / Math.max(box.h, 1)
        )
      )
    );
    const pan = {
      x: cy.width() / 2 - zoom * (box.x1 + box.w / 2),
      y: cy.height() / 2 - zoom * (box.y1 + box.h / 2),
    };
    if (!duration) {
      cy.viewport({ zoom, pan });
      return;
    }
    cy.stop(true, false);
    movable.stop(true, false);
    movable.positions((node) => before.get(node.id()) ?? node.position());
    movable.forEach((node) => {
      node.animate(
        { position: after.get(node.id()) },
        { duration, easing: "ease-in-out-cubic" }
      );
    });
    cy.animate({ zoom, pan }, { duration, easing: "ease-in-out-cubic" });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- relayout only when the shape changes
  }, [ready, structure]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!ready || !cy) return;
    cy.batch(() => {
      cy.elements().removeClass("faded lit focus match issue");
      if (showIssues) cy.nodes("[issues > 0]").addClass("issue");
      matches.forEach((id) => cy.getElementById(id).addClass("match"));
      if (path) {
        cy.elements().addClass("faded");
        cy.nodes()
          .filter((node) => path.nodes.has(node.id()))
          .removeClass("faded");
        cy.edges()
          .filter((edge) => path.edges.has(edge.id()))
          .removeClass("faded")
          .addClass("lit");
      }
      const selected = selectedId ? cy.getElementById(selectedId) : null;
      if (selected && selected.nonempty()) {
        const hood =
          selected.group() === "nodes"
            ? selected.closedNeighborhood()
            : selected.union(selected.connectedNodes());
        if (!path) {
          cy.elements().not(hood).addClass("faded");
          hood.edges().addClass("lit");
        }
        selected.addClass("focus");
      }
    });
    if (path) {
      const eles = cy
        .elements()
        .filter((element) =>
          element.isNode()
            ? path.nodes.has(element.id())
            : path.edges.has(element.id())
        );
      cy.animate({ fit: { eles, padding: 80 } }, { duration: 300 });
      return;
    }
    const selected = selectedId ? cy.getElementById(selectedId) : null;
    if (selected && selected.nonempty()) {
      const box = selected.boundingBox();
      const view = cy.extent();
      const inside =
        box.x1 >= view.x1 &&
        box.x2 <= view.x2 &&
        box.y1 >= view.y1 &&
        box.y2 <= view.y2;
      if (!inside)
        cy.animate({ center: { eles: selected } }, { duration: 300 });
    }
  }, [ready, structure, selectedId, path, matches, showIssues]);

  const zoomBy = (factor: number) => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.zoom({
      level: cy.zoom() * factor,
      renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 },
    });
  };

  return (
    <div className="relative h-full w-full">
      <div
        ref={container}
        role="img"
        aria-label={ariaLabel}
        className="h-full w-full bg-[radial-gradient(hsl(var(--border))_1px,transparent_1px)] [background-size:22px_22px]"
      />
      <div ref={sprite} hidden aria-hidden="true">
        {Object.values(KINDS).map((kind) => {
          const Icon = ENTITY_ICONS[kind];
          return <Icon key={kind} data-kind={kind} />;
        })}
      </div>
      <div ref={probes} hidden aria-hidden="true">
        {Object.entries(PALETTE).map(([role, className]) => (
          <span key={role} data-role={role} className={className} />
        ))}
      </div>
      <div className="absolute bottom-4 left-4 flex items-center overflow-hidden rounded-lg border border-border bg-background shadow-sm">
        <button
          type="button"
          className={controlClass}
          onClick={() => zoomBy(1 / 1.25)}
          aria-label={t("zoomOut")}
        >
          <Minus className="h-4 w-4" />
        </button>
        <span className="w-12 text-center text-xs tabular-nums text-muted-foreground">
          {Math.round(zoom * 100)}%
        </span>
        <button
          type="button"
          className={controlClass}
          onClick={() => zoomBy(1.25)}
          aria-label={t("zoomIn")}
        >
          <Plus className="h-4 w-4" />
        </button>
        <span className="h-5 w-px bg-border" />
        <button
          type="button"
          className={controlClass}
          onClick={() =>
            cyRef.current?.animate(
              { fit: { eles: cyRef.current.elements(), padding: 40 } },
              { duration: 300 }
            )
          }
          aria-label={t("fit")}
          title={t("fit")}
        >
          <Focus className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
