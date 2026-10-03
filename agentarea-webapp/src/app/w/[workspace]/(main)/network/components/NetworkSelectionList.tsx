"use client";

import { useMemo, useState } from "react";
import { ArrowRight, ChevronDown } from "lucide-react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import type { GraphEdge, GraphNode } from "../utils/networkGraph";

const INITIAL_VISIBLE_COUNT = 100;

interface NetworkSelectionListProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  selectedId: string | null;
  onSelectNode: (id: string) => void;
  onSelectEdge: (id: string) => void;
}

function visibleItems<T extends { id: string }>(
  items: T[],
  selectedId: string | null,
  showAll: boolean
) {
  if (showAll || items.length <= INITIAL_VISIBLE_COUNT) return items;

  const visible = items.slice(0, INITIAL_VISIBLE_COUNT);
  const selected = items.find((item) => item.id === selectedId);
  if (selected && !visible.some((item) => item.id === selected.id))
    visible.push(selected);
  return visible;
}

const itemClass =
  "flex min-h-11 w-full min-w-0 items-center justify-between gap-2 rounded-md border border-border bg-background px-2.5 py-1.5 text-left text-sm text-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary md:min-h-8";
const moreClass =
  "mt-2 min-h-11 rounded-md px-2.5 text-sm font-medium text-primary hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary md:min-h-8";

export default function NetworkSelectionList({
  nodes,
  edges,
  selectedId,
  onSelectNode,
  onSelectEdge,
}: NetworkSelectionListProps) {
  const t = useTranslations("NetworkPage.graphSelection");
  const graphText = useTranslations("NetworkPage.graph");
  const types = useTranslations("NetworkPage.orgChart");
  const peopleText = useTranslations("NetworkPage.people");
  const [showAllNodes, setShowAllNodes] = useState(false);
  const [showAllEdges, setShowAllEdges] = useState(false);
  const byId = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);
  const listedNodes = visibleItems(nodes, selectedId, showAllNodes);
  const listedEdges = visibleItems(edges, selectedId, showAllEdges);

  return (
    <details className="shrink-0 border-b border-border bg-background">
      <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 px-4 text-sm font-medium text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary md:px-5">
        <span>{t("title")}</span>
        <span className="shrink-0 text-xs font-normal text-muted-foreground">
          {nodes.length} · {edges.length}
        </span>
        <ChevronDown aria-hidden="true" className="h-4 w-4 shrink-0 text-muted-foreground" />
      </summary>
      <div className="max-h-[min(20vh,12rem)] overflow-y-auto border-t border-border px-4 py-3 md:max-h-[min(35vh,20rem)] md:px-5">
        <div className="grid min-w-0 grid-cols-1 gap-4 md:grid-cols-2">
          <section className="min-w-0">
            <h3 className="mb-2 text-xs font-semibold text-muted-foreground">
              {t("nodes", { count: nodes.length })}
            </h3>
            <ul className="space-y-1">
              {listedNodes.map((node) => {
                const current = selectedId === node.id;
                return (
                  <li key={node.id} className="min-w-0">
                    <button
                      type="button"
                      aria-current={current ? "true" : undefined}
                      onClick={() => onSelectNode(node.id)}
                      className={cn(itemClass, current && "border-primary bg-primary/10")}
                    >
                      <span className="min-w-0 truncate font-medium">{node.label}</span>
                      <span className="shrink-0 text-xs text-muted-foreground">
                        {node.kind === "person"
                          ? peopleText("title")
                          : types.has(`types.${node.kind}`)
                            ? types(`types.${node.kind}`)
                            : node.kind}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
            {nodes.length > INITIAL_VISIBLE_COUNT && (
              <button
                type="button"
                onClick={() => setShowAllNodes((value) => !value)}
                className={moreClass}
              >
                {t(showAllNodes ? "showLess" : "showMore")}
              </button>
            )}
          </section>

          <section className="min-w-0">
            <h3 className="mb-2 text-xs font-semibold text-muted-foreground">
              {t("relationships", { count: edges.length })}
            </h3>
            <ul className="space-y-1">
              {listedEdges.map((edge) => {
                const current = selectedId === edge.id;
                const source = byId.get(edge.source)?.label ?? edge.source;
                const target = byId.get(edge.target)?.label ?? edge.target;
                const relation =
                  edge.relation === "person_access"
                    ? graphText(edge.off ? "denied" : "allowed")
                    : types.has(`relations.${edge.relation}`)
                      ? types(`relations.${edge.relation}`)
                      : edge.relation;
                return (
                  <li key={edge.id} className="min-w-0">
                    <button
                      type="button"
                      aria-current={current ? "true" : undefined}
                      aria-label={t("relationshipLabel", {
                        source,
                        target,
                        relation,
                      })}
                      onClick={() => onSelectEdge(edge.id)}
                      className={cn(
                        itemClass,
                        "justify-start",
                        current && "border-primary bg-primary/10"
                      )}
                    >
                      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                        <span className="flex min-w-0 items-center gap-1.5 truncate font-medium">
                          <span className="truncate">{source}</span>
                          <ArrowRight
                            aria-hidden="true"
                            className="h-3.5 w-3.5 shrink-0"
                          />
                          <span className="truncate">{target}</span>
                        </span>
                        <span className="truncate text-xs text-muted-foreground">
                          {relation}
                        </span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
            {edges.length > INITIAL_VISIBLE_COUNT && (
              <button
                type="button"
                onClick={() => setShowAllEdges((value) => !value)}
                className={moreClass}
              >
                {t(showAllEdges ? "showLess" : "showMore")}
              </button>
            )}
          </section>
        </div>
      </div>
    </details>
  );
}
