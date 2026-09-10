"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import type cytoscape from "cytoscape";
import {
  buildCytoscapeElements,
  getCanvasBounds,
  getEdgePoints,
} from "../utils/cytoscapeElements";
import type {
  CanvasControls,
  CanvasEdge,
  CanvasNode,
  CanvasPoint,
} from "./networkCanvasTypes";

interface Props<Data extends Record<string, unknown>> {
  nodes: CanvasNode<Data>[];
  edges: CanvasEdge[];
  focusIds: string[] | null;
  horizontal: boolean;
  detailsOpen: boolean;
  ariaLabel: string;
  renderNode: (node: CanvasNode<Data>) => ReactNode;
  onReady: (controls: CanvasControls | null) => void;
  onZoom: (zoom: number) => void;
  onNodeClick: (id: string) => void;
  onEdgeClick: (id: string) => void;
  onPaneClick: () => void;
  onEscape: () => void;
}

const styles: cytoscape.StylesheetJson = [
  {
    selector: "node",
    style: {
      width: "data(width)",
      height: "data(height)",
      opacity: 0,
      events: "no",
      "border-width": 0,
    },
  },
  {
    selector: "edge",
    style: {
      "curve-style": "round-segments",
      "segment-weights": "data(weights)",
      "segment-distances": "data(distances)",
      "segment-radii": [10],
      "edge-distances": "node-position",
      "source-endpoint": "data(sourceEndpoint)",
      "target-endpoint": "data(targetEndpoint)",
      "line-color": "data(stroke)",
      "target-arrow-color": "data(stroke)",
      "target-arrow-shape": "triangle",
      "arrow-scale": 0.75,
      width: "data(width)",
      opacity: (edge: cytoscape.EdgeSingular) => Number(edge.data("opacity")),
      "z-index": 1,
    },
  },
  {
    selector: "edge[?dashed]",
    style: { "line-style": "dashed", "line-dash-pattern": [4, 4] },
  },
  {
    selector: 'edge[curveStyle = "straight"]',
    style: { "curve-style": "straight" },
  },
  { selector: "edge[?selected]", style: { "z-index": 3 } },
];

export default function NetworkCanvas<Data extends Record<string, unknown>>(
  props: Props<Data>
) {
  const {
    nodes,
    edges,
    focusIds,
    detailsOpen,
    horizontal,
    renderNode,
    ariaLabel,
  } = props;
  const t = useTranslations("NetworkPage.integration");
  const containerRef = useRef<HTMLDivElement>(null);
  const regionLayer = useRef<HTMLDivElement>(null);
  const cardLayer = useRef<HTMLDivElement>(null);
  const cyRef = useRef<cytoscape.Core | null>(null);
  const latest = useRef(props);
  latest.current = props;
  const [ready, setReady] = useState(false);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const drag = useRef<{
    x: number;
    y: number;
    pan: cytoscape.Position;
    moved: boolean;
  } | null>(null);
  const ignoreClick = useRef(false);
  const { x, y, width, height } = getCanvasBounds(nodes, focusIds);
  const focused = !!focusIds?.some((id) =>
    nodes.some((node) => node.id === id)
  );
  const elements = useMemo(
    () => buildCytoscapeElements(nodes, edges),
    [nodes, edges]
  );

  useEffect(() => {
    const host = containerRef.current;
    if (!host) return;
    let disposed = false;
    setError(false);
    setReady(false);
    let cy: cytoscape.Core | null = null;
    void import("cytoscape")
      .then(({ default: createCytoscape }) => {
        if (disposed) return;
        cy = createCytoscape({
          container: host,
          elements: [],
          style: styles,
          layout: { name: "preset", fit: false },
          minZoom: 0.1,
          maxZoom: 1.8,
          autoungrabify: true,
          autounselectify: true,
          boxSelectionEnabled: false,
          pixelRatio: "auto",
        });
        cyRef.current = cy;
        const sync = () => {
          if (!cy) return;
          const pan = cy.pan(),
            zoom = cy.zoom();
          const transform = `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`;
          if (host.parentElement) {
            host.parentElement.style.backgroundSize = `${24 * zoom}px ${24 * zoom}px`;
            host.parentElement.style.backgroundPosition = `${pan.x}px ${pan.y}px`;
          }
          for (const layer of [regionLayer.current, cardLayer.current])
            if (layer) layer.style.transform = transform;
          latest.current.onZoom(zoom);
        };
        cy.on("viewport", sync);
        cy.on("tap", "edge", (event) =>
          latest.current.onEdgeClick(event.target.data("originalId"))
        );
        cy.on("tap", (event) => {
          if (event.target === cy) latest.current.onPaneClick();
        });
        cy.on("mouseover", "edge", () => {
          host.style.cursor = "pointer";
        });
        cy.on("mouseout", "edge", () => {
          host.style.cursor = "default";
        });
        latest.current.onReady({
          fit: () =>
            fitCanvas(cy, getCanvasBounds(latest.current.nodes), false),
          zoomBy: (factor) => {
            if (!cy) return;
            cy.zoom({
              level: Math.max(
                cy.minZoom(),
                Math.min(cy.maxZoom(), cy.zoom() * factor)
              ),
              renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 },
            });
          },
        });
        sync();
        setReady(true);
      })
      .catch(() => {
        if (!disposed) setError(true);
      });
    return () => {
      disposed = true;
      cy?.destroy();
      cyRef.current = null;
      latest.current.onReady(null);
    };
  }, [attempt]);

  useEffect(() => {
    const layer = cardLayer.current,
      host = containerRef.current;
    if (!ready || !layer || !host) return;
    const forwardWheel = (event: WheelEvent) => {
      event.preventDefault();
      // Use Cytoscape's wheel handling for the same device calibration,
      // delta-mode normalization, pointer anchor and zoom limits as the canvas.
      host.dispatchEvent(
        new WheelEvent("wheel", {
          bubbles: true,
          cancelable: true,
          clientX: event.clientX,
          clientY: event.clientY,
          deltaX: event.deltaX,
          deltaY: event.deltaY,
          deltaZ: event.deltaZ,
          deltaMode: event.deltaMode,
          ctrlKey: event.ctrlKey,
          altKey: event.altKey,
          metaKey: event.metaKey,
          shiftKey: event.shiftKey,
        })
      );
    };
    layer.addEventListener("wheel", forwardWheel, { passive: false });
    return () => layer.removeEventListener("wheel", forwardWheel);
  }, [ready]);

  useEffect(() => {
    const layer = cardLayer.current,
      host = containerRef.current;
    if (!ready || !layer || !host) return;
    let gesture: { first: Touch; forwarded: boolean } | null = null;
    const forward = (
      type: string,
      touches: Touch[],
      changedTouches: Touch[]
    ) => {
      host.querySelector("canvas")?.dispatchEvent(
        new TouchEvent(type, {
          bubbles: true,
          cancelable: true,
          touches,
          targetTouches: touches,
          changedTouches,
        })
      );
    };
    const start = (event: TouchEvent) => {
      if (!event.touches.length) return;
      if (event.touches.length === 1 || !gesture) {
        gesture = { first: event.touches[0], forwarded: false };
        ignoreClick.current = false;
      }
      if (event.touches.length > 1 || gesture.forwarded) {
        gesture.forwarded = true;
        ignoreClick.current = true;
        event.preventDefault();
        forward(
          "touchstart",
          Array.from(event.touches),
          Array.from(event.changedTouches)
        );
      }
    };
    const move = (event: TouchEvent) => {
      if (!gesture || !event.touches.length) return;
      if (!gesture.forwarded) {
        const touch = event.touches[0];
        if (
          event.touches.length === 1 &&
          Math.hypot(
            touch.clientX - gesture.first.clientX,
            touch.clientY - gesture.first.clientY
          ) < 8
        )
          return;
        gesture.forwarded = true;
        const initial =
          event.touches.length > 1
            ? Array.from(event.touches)
            : [gesture.first];
        // Start capture only once a gesture is clear, keeping stationary HTML
        // taps native. Cytoscape already handles subsequent move/end on window.
        forward("touchstart", initial, initial);
        forward(
          "touchmove",
          Array.from(event.touches),
          Array.from(event.changedTouches)
        );
        event.stopPropagation();
      }
      ignoreClick.current = true;
      event.preventDefault();
    };
    const canvasStart = () => {
      // A second finger may land on the canvas after the first touched a card.
      if (gesture) {
        gesture.forwarded = true;
        ignoreClick.current = true;
      }
    };
    const finish = (event: TouchEvent) => {
      if (!event.touches.length) gesture = null;
    };
    const cancel = () => {
      gesture = null;
    };
    layer.addEventListener("touchstart", start, { passive: false });
    layer.addEventListener("touchmove", move, { passive: false });
    host.addEventListener("touchstart", canvasStart);
    window.addEventListener("touchend", finish);
    window.addEventListener("touchcancel", cancel);
    return () => {
      layer.removeEventListener("touchstart", start);
      layer.removeEventListener("touchmove", move);
      host.removeEventListener("touchstart", canvasStart);
      window.removeEventListener("touchend", finish);
      window.removeEventListener("touchcancel", cancel);
    };
  }, [ready]);

  useEffect(() => {
    const cy = cyRef.current,
      host = containerRef.current;
    if (!ready || !cy || !host) return;
    const apply = () => {
      const swatch = document.createElement("span");
      swatch.style.display = "none";
      host.appendChild(swatch);
      const colors = new Map<string, string>();
      const colored = elements.map((element) => {
        if (element.group !== "edges") return element;
        const color = String(element.data.stroke);
        if (!colors.has(color)) {
          swatch.style.color = color;
          colors.set(color, getComputedStyle(swatch).color);
        }
        return {
          ...element,
          data: { ...element.data, stroke: colors.get(color) },
        };
      });
      swatch.remove();
      cy.json({ elements: colored });
    };
    apply();
    const theme = new MutationObserver(apply);
    theme.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class", "style"],
    });
    return () => theme.disconnect();
  }, [elements, ready]);

  useEffect(() => {
    const cy = cyRef.current,
      host = containerRef.current;
    if (!ready || !cy || !host || !width || !height) return;
    let frame = 0;
    const fit = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        cy.resize();
        fitCanvas(cy, { x, y, width, height }, focused);
      });
    };
    fit();
    const observer = new ResizeObserver(fit);
    observer.observe(host);
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
    };
  }, [ready, x, y, width, height, focused, detailsOpen, horizontal]);

  const ensureVisible = (node: CanvasNode<Data>) => {
    const cy = cyRef.current;
    if (!cy) return;
    const pan = cy.pan(),
      zoom = cy.zoom();
    const left = node.position.x * zoom + pan.x,
      top = node.position.y * zoom + pan.y;
    if (
      left < 0 ||
      top < 0 ||
      left + node.width * zoom > cy.width() ||
      top + node.height * zoom > cy.height()
    )
      cy.center(cy.getElementById(`n:${node.id}`));
  };
  const ensurePointVisible = (point: CanvasPoint) => {
    const cy = cyRef.current;
    if (!cy) return;
    const zoom = cy.zoom(),
      pan = cy.pan(),
      x = point.x * zoom + pan.x,
      y = point.y * zoom + pan.y;
    const margin = 32;
    if (
      x < margin ||
      y < margin ||
      x > cy.width() - margin ||
      y > cy.height() - margin
    )
      cy.pan({
        x: cy.width() / 2 - point.x * zoom,
        y: cy.height() / 2 - point.y * zoom,
      });
  };
  return (
    <div
      className="relative h-full w-full overflow-clip"
      data-network-renderer="cytoscape"
      aria-label={ariaLabel}
      style={{
        backgroundImage:
          "radial-gradient(circle, hsl(var(--border)) 1px, transparent 1px)",
        backgroundSize: "24px 24px",
      }}
    >
      <div
        ref={regionLayer}
        className="pointer-events-none absolute left-0 top-0 origin-top-left"
      >
        {nodes
          .filter((node) => node.type === "region")
          .sort((a, b) => (a.zIndex ?? 0) - (b.zIndex ?? 0))
          .map((node) => (
            <div
              key={node.id}
              data-network-node={node.id}
              data-node-type="region"
              className="absolute"
              style={{
                left: node.position.x,
                top: node.position.y,
                width: node.width,
                height: node.height,
              }}
            >
              {renderNode(node)}
            </div>
          ))}
      </div>
      <div ref={containerRef} className="absolute inset-0" aria-hidden="true" />
      <div
        ref={cardLayer}
        className="pointer-events-none absolute left-0 top-0 origin-top-left"
      >
        {nodes
          .filter((node) => node.type !== "region")
          .map((node) => (
            <div
              key={node.id}
              data-network-node={node.id}
              data-node-type={node.type}
              className="network-map-node pointer-events-auto absolute touch-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
              role={node.focusable === false ? undefined : "group"}
              tabIndex={node.focusable === false ? undefined : 0}
              aria-label={node.ariaLabel}
              style={{
                left: node.position.x,
                top: node.position.y,
                width: node.width,
                height: node.height,
              }}
              onFocus={() => ensureVisible(node)}
              onPointerDown={(event) => {
                if (
                  event.pointerType === "touch" ||
                  event.button !== 0 ||
                  (event.target as Element).closest("button,input,select,a")
                )
                  return;
                const cy = cyRef.current;
                if (!cy) return;
                ignoreClick.current = false;
                drag.current = {
                  x: event.clientX,
                  y: event.clientY,
                  pan: cy.pan(),
                  moved: false,
                };
                event.currentTarget.setPointerCapture(event.pointerId);
              }}
              onPointerMove={(event) => {
                if (event.pointerType === "touch") return;
                const start = drag.current,
                  cy = cyRef.current;
                if (!start || !cy) return;
                const dx = event.clientX - start.x,
                  dy = event.clientY - start.y;
                if (Math.hypot(dx, dy) > 3) start.moved = true;
                if (start.moved)
                  cy.pan({ x: start.pan.x + dx, y: start.pan.y + dy });
              }}
              onPointerUp={(event) => {
                if (event.pointerType === "touch") return;
                ignoreClick.current = !!drag.current?.moved;
                drag.current = null;
              }}
              onPointerCancel={(event) => {
                if (event.pointerType === "touch") return;
                drag.current = null;
                ignoreClick.current = false;
              }}
              onClick={() => {
                if (ignoreClick.current) {
                  ignoreClick.current = false;
                  return;
                }
                if (node.type !== "people") latest.current.onNodeClick(node.id);
              }}
              onKeyDown={(event) => {
                if (event.target !== event.currentTarget) return;
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  latest.current.onNodeClick(node.id);
                } else if (event.key === "Escape") latest.current.onEscape();
              }}
            >
              {renderNode(node)}
            </div>
          ))}
        {edges.map((edge) => {
          const points = getEdgePoints(edge, nodes);
          if (!points.length) return null;
          const point =
            edge.data.labelPosition ?? points[Math.floor(points.length / 2)];
          return (
            <button
              key={edge.id}
              type="button"
              data-network-edge={edge.id}
              aria-label={edge.ariaLabel ?? `${edge.source} → ${edge.target}`}
              aria-pressed={edge.selected ?? false}
              className={
                edge.label
                  ? "pointer-events-auto absolute whitespace-nowrap rounded bg-background px-1.5 py-1 text-[11px] text-foreground focus-visible:ring-2 focus-visible:ring-primary"
                  : "pointer-events-none absolute h-5 w-5 rounded opacity-0 focus-visible:pointer-events-auto focus-visible:bg-background focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-primary"
              }
              style={{
                left: point.x,
                top: point.y,
                transform: "translate(-50%, -100%)",
              }}
              onFocus={() => ensurePointVisible(point)}
              onClick={() => latest.current.onEdgeClick(edge.id)}
              onKeyDown={(event) => {
                if (event.key === "Escape") latest.current.onEscape();
              }}
            >
              {edge.label}
            </button>
          );
        })}
      </div>
      {error && (
        <div
          role="alert"
          className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-3 bg-background"
        >
          <p className="text-sm">{t("loadError")}</p>
          <button
            className="text-sm text-primary underline"
            onClick={() => setAttempt((value) => value + 1)}
          >
            {t("retry")}
          </button>
        </div>
      )}
    </div>
  );
}

function fitCanvas(
  cy: cytoscape.Core | null,
  bounds: { x: number; y: number; width: number; height: number },
  focused: boolean
) {
  if (!cy || !bounds.width || !bounds.height) return;
  const padding = focused ? 0.8 : 0.12;
  const zoom = Math.max(
    cy.minZoom(),
    Math.min(
      1,
      cy.width() / (bounds.width * (1 + padding)),
      cy.height() / (bounds.height * (1 + padding))
    )
  );
  cy.viewport({
    zoom,
    pan: {
      x: cy.width() / 2 - (bounds.x + bounds.width / 2) * zoom,
      y: cy.height() / 2 - (bounds.y + bounds.height / 2) * zoom,
    },
  });
}
