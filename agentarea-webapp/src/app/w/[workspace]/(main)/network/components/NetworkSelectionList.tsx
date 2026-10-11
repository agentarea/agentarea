"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { ArrowRight } from "lucide-react";
import { AgentAvatar } from "@/components/AgentAvatar";
import EntityMark from "@/components/EntityMark";
import { CollapsibleGroup } from "@/components/ui/group-header";
import { InteractiveListRow } from "@/components/ui/interactive-list-row";
import { EntityIcon } from "@/lib/entity-icons";
import type { NetworkNodeData } from "../types";
import { getNodeIdentity } from "../utils/networkConnections";
import type { GraphEdge, GraphKind, GraphNode } from "../utils/networkGraph";

const INITIAL_VISIBLE_COUNT = 100;

const GROUPS: { key: string; kinds: GraphKind[] }[] = [
  { key: "agents", kinds: ["agent"] },
  { key: "triggers", kinds: ["trigger"] },
  { key: "resources", kinds: ["mcp_instance", "openapi_connection", "skill"] },
  { key: "people", kinds: ["person"] },
];

interface NetworkSelectionListProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  topologyNodes: NetworkNodeData[];
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

const moreClass =
  "min-h-9 w-full px-4 text-left text-[12.5px] font-medium text-primary hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary";

/**
 * The graph as rows: every node grouped by kind, then every relationship. The
 * list view of the network, and the keyboard path to anything on the canvas.
 */
export default function NetworkSelectionList({
  nodes,
  edges,
  topologyNodes,
  selectedId,
  onSelectNode,
  onSelectEdge,
}: NetworkSelectionListProps) {
  const t = useTranslations("NetworkPage.graphSelection");
  const graphText = useTranslations("NetworkPage.graph");
  const types = useTranslations("NetworkPage.orgChart");
  const peopleText = useTranslations("NetworkPage.people");
  const [showAll, setShowAll] = useState(false);
  const byId = useMemo(
    () => new Map(nodes.map((node) => [node.id, node])),
    [nodes]
  );
  const topologyById = useMemo(
    () => new Map(topologyNodes.map((node) => [node.id, node])),
    [topologyNodes]
  );
  const listedEdges = visibleItems(edges, selectedId, showAll);

  const kindLabel = (kind: GraphKind) =>
    kind === "person"
      ? peopleText("title")
      : types.has(`types.${kind}`)
        ? types(`types.${kind}`)
        : kind;

  const mark = (node: GraphNode) => {
    if (node.kind === "agent")
      return <AgentAvatar agent={{ id: node.id, name: node.label }} />;
    const source = topologyById.get(node.id);
    if (!source)
      return (
        <EntityIcon
          kind="person"
          className="h-6 w-6 rounded-md p-1 text-muted-foreground"
        />
      );
    return (
      <EntityMark
        identity={getNodeIdentity(source)}
        className="h-6 w-6 shrink-0 rounded-md"
        glyphClassName="p-1 text-muted-foreground"
      />
    );
  };

  return (
    <div className="h-full overflow-y-auto bg-background">
      {GROUPS.map(({ key, kinds }) => {
        const members = nodes.filter((node) => kinds.includes(node.kind));
        if (members.length === 0) return null;
        return (
          <CollapsibleGroup
            key={key}
            label={t(`groups.${key}`)}
            count={members.length}
          >
            {members.map((node) => (
              <InteractiveListRow
                key={node.id}
                start={mark(node)}
                selected={selectedId === node.id}
                onClick={() => onSelectNode(node.id)}
                end={
                  kinds.length > 1 && (
                    <span className="text-[11.5px] text-muted-foreground">
                      {kindLabel(node.kind)}
                    </span>
                  )
                }
              >
                <span className="truncate text-[13px] font-medium">
                  {node.label}
                </span>
              </InteractiveListRow>
            ))}
          </CollapsibleGroup>
        );
      })}
      {edges.length > 0 && (
        <CollapsibleGroup
          label={t("groups.links")}
          count={edges.length}
          defaultOpen={false}
        >
          {listedEdges.map((edge) => {
            const source = byId.get(edge.source)?.label ?? edge.source;
            const target = byId.get(edge.target)?.label ?? edge.target;
            const relation =
              edge.relation === "person_access"
                ? graphText(edge.off ? "denied" : "allowed")
                : types.has(`relations.${edge.relation}`)
                  ? types(`relations.${edge.relation}`)
                  : edge.relation;
            return (
              <InteractiveListRow
                key={edge.id}
                selected={selectedId === edge.id}
                onClick={() => onSelectEdge(edge.id)}
                contentClassName="gap-1.5"
                end={
                  <span className="text-[11.5px] text-muted-foreground">
                    {relation}
                  </span>
                }
              >
                <span className="truncate text-[13px]">{source}</span>
                <ArrowRight
                  aria-hidden="true"
                  className="h-3.5 w-3.5 shrink-0 text-muted-foreground"
                />
                <span className="truncate text-[13px]">{target}</span>
              </InteractiveListRow>
            );
          })}
          {edges.length > INITIAL_VISIBLE_COUNT && (
            <button
              type="button"
              onClick={() => setShowAll((value) => !value)}
              className={moreClass}
            >
              {t(showAll ? "showLess" : "showMore")}
            </button>
          )}
        </CollapsibleGroup>
      )}
    </div>
  );
}
