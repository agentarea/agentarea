"use client";

import { Box } from "lucide-react";
import { cn } from "@/lib/utils";
import type { GraphLayout, PositionedNode } from "./graph-layout";
import { formatCount } from "./graph-layout";
import styles from "./access-control.module.css";

interface GraphPaneProps {
  layout: GraphLayout;
  selectedNodeId: string | null;
  highlightedNodeIds: Set<string>;
  highlightedEdgeKeys: Set<string>;
  onSelectNode: (nodeId: string) => void;
}

function relationEdgeClass(relation: string): string {
  switch (relation) {
    case "user":
      return styles.edgePermUser;
    case "editor":
      return styles.edgePermEditor;
    case "owner":
      return styles.edgePermOwner;
    case "connect":
      return styles.edgePermConnect;
    default:
      return styles.edgeMember;
  }
}

function relationLabelClass(relation: string): string | undefined {
  switch (relation) {
    case "user":
      return styles.elabelUser;
    case "editor":
      return styles.elabelEditor;
    case "owner":
      return styles.elabelOwner;
    case "connect":
      return styles.elabelConnect;
    default:
      return undefined;
  }
}

function nodeInitials(node: PositionedNode): string {
  const letters = node.name
    .split(/[\s-]+/)
    .map((part) => part[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("");
  return (letters || node.name.slice(0, 2)).toUpperCase();
}

export default function GraphPane({
  layout,
  selectedNodeId,
  highlightedNodeIds,
  highlightedEdgeKeys,
  onSelectNode,
}: GraphPaneProps) {
  const hasHighlight = highlightedNodeIds.size > 0;

  return (
    <div className={styles.graphpane}>
      <div
        className={styles.canvas}
        style={{ width: layout.width, height: layout.height }}
      >
        {layout.columnLabels.map((col) => (
          <div
            key={col.label}
            className={styles.collabel}
            style={{ left: col.x }}
          >
            {col.label}
          </div>
        ))}

        <svg className={styles.edges}>
          {layout.edges.map((edge) => {
            const key = `${edge.from}>${edge.to}`;
            const on = highlightedEdgeKeys.has(key);
            const dim = hasHighlight && !on;
            return (
              <path
                key={key}
                d={edge.path}
                className={cn(
                  styles.edge,
                  relationEdgeClass(edge.relation),
                  on && styles.edgeOn,
                  dim && styles.edgeDim
                )}
              />
            );
          })}
        </svg>

        {layout.edges.map((edge) => {
          const key = `${edge.from}>${edge.to}`;
          const dim = hasHighlight && !highlightedEdgeKeys.has(key);
          return (
            <div
              key={`label-${key}`}
              className={cn(
                styles.elabel,
                relationLabelClass(edge.relation),
                dim && styles.elabelDim
              )}
              style={{ left: edge.labelX, top: edge.labelY }}
            >
              {edge.relation}
            </div>
          );
        })}

        {layout.nodes.map((node) => {
          const on = node.id === selectedNodeId || highlightedNodeIds.has(node.id);
          const dim = hasHighlight && !highlightedNodeIds.has(node.id);
          const countLabel = formatCount(node.count);
          return (
            <button
              type="button"
              key={node.id}
              className={cn(
                styles.node,
                on && styles.nodeOn,
                dim && styles.nodeDim
              )}
              style={{
                left: node.x,
                top: node.y,
                width: node.w,
                height: node.h,
              }}
              onClick={() => onSelectNode(node.id)}
            >
              <span className={styles.nIc} style={{ background: node.color }}>
                {node.kind === "agent" ? (
                  nodeInitials(node)
                ) : (
                  <Box className="h-3.5 w-3.5" strokeWidth={2} />
                )}
              </span>
              <span className={styles.nH}>
                <span className={styles.nName}>{node.name}</span>
                <span className={styles.nSub}>{node.subtitle}</span>
              </span>
              {countLabel && <span className={styles.cnt}>{countLabel}</span>}
            </button>
          );
        })}
      </div>
    </div>
  );
}
