"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useTranslations } from "next-intl";
import { Info, X } from "lucide-react";
import type {
  EffectivePolicy,
  NetworkPeopleAccessResponse,
} from "@/api/client/types.gen";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { useViewerCapabilities } from "@/components/ViewerCapabilities";
import { cn } from "@/lib/utils";
import type { NetworkActionResult } from "../actions";
import NetworkCanvas from "../components/NetworkCanvas";
import NetworkConnectionPanel from "../components/NetworkConnectionPanel";
import NetworkPeoplePanel from "../components/NetworkPeoplePanel";
import NetworkRoutePanel from "../components/NetworkRoutePanel";
import NetworkSelectionList from "../components/NetworkSelectionList";
import { useNetwork } from "../NetworkProvider";
import type { NetworkNodeData, TopologyResponse } from "../types";
import { useNetworkPeople } from "../useNetworkPeople";
import {
  buildNetworkGraph,
  graphForLens,
  isResource,
  pathThrough,
  personNodeId,
  personUserId,
  searchGraph,
  type GraphLens,
} from "../utils/networkGraph";

export interface NetworkGraphViewProps {
  lens: GraphLens;
  topology: TopologyResponse;
  loadPolicy?: (
    agentId: string
  ) => Promise<NetworkActionResult<EffectivePolicy>>;
  loadPeopleAccess?: () => Promise<
    NetworkActionResult<NetworkPeopleAccessResponse>
  >;
  selectedNodeId: string | null;
  onSelectNode: (node: NetworkNodeData | null) => void;
}

export default function NetworkGraphView({
  lens,
  topology,
  loadPolicy,
  loadPeopleAccess,
  selectedNodeId,
  onSelectNode,
}: NetworkGraphViewProps) {
  const t = useTranslations("NetworkPage.graph");
  const peopleText = useTranslations("NetworkPage.people");
  const accessText = useTranslations("NetworkPage.accessDetails");
  const { canAdminister } = useViewerCapabilities();
  const people = useNetworkPeople(canAdminister, loadPeopleAccess, topology);

  const { mode, query, showIssues, showPeople } = useNetwork();
  const [edgeId, setEdgeId] = useState<string | null>(null);
  const [personId, setPersonId] = useState<string | null>(null);
  const [peopleOpen, setPeopleOpen] = useState(false);
  const [pathOf, setPathOf] = useState<string | null>(null);

  const graph = useMemo(
    () => buildNetworkGraph(topology, people.data),
    [topology, people.data]
  );
  const visible = useMemo(
    () => graphForLens(graph, lens, showPeople),
    [graph, lens, showPeople]
  );
  const visibleIds = useMemo(
    () => new Set(visible.nodes.map((node) => node.id)),
    [visible]
  );
  const path = useMemo(
    () =>
      pathOf && visibleIds.has(pathOf) ? pathThrough(visible, pathOf) : null,
    [visible, visibleIds, pathOf]
  );
  const results = useMemo(() => searchGraph(visible, query), [visible, query]);
  const matches = useMemo(
    () => new Set(results.map((node) => node.id)),
    [results]
  );
  const listed = useMemo(
    () =>
      query.trim()
        ? {
            nodes: results,
            edges: visible.edges.filter(
              (item) => matches.has(item.source) || matches.has(item.target)
            ),
          }
        : visible,
    [query, results, matches, visible]
  );

  const edge = visible.edges.find((item) => item.id === edgeId);
  const person = people.data?.people.find((item) => item.user_id === personId);
  const node =
    !edge && selectedNodeId
      ? topology.nodes.find((item) => item.id === selectedNodeId)
      : undefined;
  const nodeIssues =
    graph.nodes.find((item) => item.id === node?.id)?.issues ?? [];
  const pathNode = topology.nodes.find((item) => item.id === pathOf);

  const clear = useCallback(() => {
    setEdgeId(null);
    setPersonId(null);
    setPeopleOpen(false);
    setPathOf(null);
    onSelectNode(null);
  }, [onSelectNode]);

  const selectPerson = useCallback(
    (userId: string) => {
      setEdgeId(null);
      setPathOf(null);
      setPersonId(userId);
      setPeopleOpen(true);
      onSelectNode(null);
    },
    [onSelectNode]
  );

  const selectNode = useCallback(
    (id: string) => {
      const userId = personUserId(id);
      if (userId) {
        selectPerson(userId);
        return;
      }
      const target = topology.nodes.find((item) => item.id === id);
      if (!target) return;
      setEdgeId(null);
      setPeopleOpen(false);
      setPersonId(null);
      if (pathOf && pathOf !== id) setPathOf(null);
      onSelectNode(target);
    },
    [topology.nodes, onSelectNode, selectPerson, pathOf]
  );

  const selectEdge = useCallback(
    (id: string) => {
      setEdgeId(id);
      setPeopleOpen(false);
      onSelectNode(null);
    },
    [onSelectNode]
  );

  // Turning people on before their access has loaded opens the panel that
  // says so; turning them off drops a selected person with them.
  useEffect(() => {
    if (showPeople && people.status !== "ready") setPeopleOpen(true);
    if (!showPeople) setPersonId(null);
  }, [showPeople, people.status]);

  const canvasSelection =
    edgeId ?? (personId ? personNodeId(personId) : null) ?? selectedNodeId;
  const routeSource = edge
    ? personUserId(edge.source) && person
      ? {
          label:
            person.display_name ||
            person.email ||
            peopleText("unnamed", { id: person.user_id.slice(0, 8) }),
          type: "person" as const,
        }
      : topology.nodes.find((item) => item.id === edge.source)
    : undefined;
  const routeTarget = edge
    ? topology.nodes.find((item) => item.id === edge.target)
    : undefined;

  const counts = {
    agents: visible.nodes.filter((item) => item.kind === "agent").length,
    resources: visible.nodes.filter((item) => isResource(item.kind)).length,
    triggers: visible.nodes.filter((item) => item.kind === "trigger").length,
    links: visible.edges.length,
  };

  const legend = (
    <>
      <Legend swatch="h-2.5 w-2.5 rounded-full bg-primary">
        {t("legend.agent")}
      </Legend>
      <Legend swatch="h-2.5 w-2.5 rounded-full border-2 border-emerald-600 dark:border-emerald-400">
        {t("legend.internal")}
      </Legend>
      <Legend swatch="h-2.5 w-2.5 rounded-full border-2 border-amber-600 dark:border-amber-400">
        {t("legend.external")}
      </Legend>
      <Legend swatch="h-2 w-2 rotate-45 bg-violet-600 dark:bg-violet-400">
        {t("legend.trigger")}
      </Legend>
      <Legend swatch="w-5 border-t-2 border-primary">
        {t("legend.delegates")}
      </Legend>
      <Legend swatch="w-5 border-t-2 border-dashed border-muted-foreground">
        {t("legend.uses")}
      </Legend>
      <Legend swatch="w-5 border-t-2 border-dotted border-violet-600 dark:border-violet-400">
        {t("legend.starts")}
      </Legend>
      {lens === "flow" && (
        <>
          <Legend swatch="w-5 border-t-2 border-muted-foreground">
            {t("legend.inbound")}
          </Legend>
          <Legend swatch="w-5 border-t-2 border-amber-600 dark:border-amber-400">
            {t("legend.outbound")}
          </Legend>
        </>
      )}
    </>
  );

  return (
    <div className="flex h-full min-h-0 w-full flex-col bg-layoutBackground">
      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <div className="relative min-h-0 min-w-0 flex-1 overflow-hidden">
          {mode === "list" ? (
            <NetworkSelectionList
              nodes={listed.nodes}
              edges={listed.edges}
              topologyNodes={topology.nodes}
              selectedId={canvasSelection}
              onSelectNode={selectNode}
              onSelectEdge={selectEdge}
            />
          ) : visible.nodes.length === 0 ? (
            <div className="flex h-full items-center justify-center px-6 text-center text-sm font-medium">
              {t(`lenses.${lens}.empty`)}
            </div>
          ) : (
            <NetworkCanvas
              graph={visible}
              nodes={topology.nodes}
              lens={lens}
              selectedId={canvasSelection}
              path={path}
              matches={matches}
              showIssues={showIssues}
              ariaLabel={t(`lenses.${lens}.title`)}
              onSelectNode={selectNode}
              onSelectEdge={selectEdge}
              onClear={clear}
            />
          )}
          {mode === "graph" && pathNode && (
            <button
              type="button"
              onClick={() => setPathOf(null)}
              className="absolute left-4 top-4 flex max-w-[calc(100%-2rem)] items-center gap-2 rounded-md border border-border bg-background px-2.5 py-1.5 text-xs shadow-sm hover:bg-muted"
              aria-label={accessText("clearFocus")}
            >
              <span className="truncate">
                {accessText("focusedOn", { name: pathNode.label })}
              </span>
              <X className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            </button>
          )}
          {mode === "graph" && visible.nodes.length > 0 && (
            <Popover>
              <PopoverTrigger asChild>
                <button
                  type="button"
                  className="absolute right-4 top-4 flex h-9 items-center gap-1.5 rounded-lg border border-border bg-background px-3 text-xs text-muted-foreground shadow-sm hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                >
                  <Info className="h-3.5 w-3.5" />
                  {t("legendTitle")}
                </button>
              </PopoverTrigger>
              <PopoverContent
                align="end"
                side="bottom"
                className="w-64 space-y-3 p-3 text-xs text-muted-foreground"
              >
                <div className="grid grid-cols-2 gap-x-3 gap-y-1 tabular-nums">
                  <span>{t("counts.agents", { count: counts.agents })}</span>
                  <span>
                    {t("counts.resources", { count: counts.resources })}
                  </span>
                  <span>
                    {t("counts.triggers", { count: counts.triggers })}
                  </span>
                  <span>{t("counts.links", { count: counts.links })}</span>
                </div>
                <div className="h-px bg-border" />
                <div className="grid gap-1.5">{legend}</div>
              </PopoverContent>
            </Popover>
          )}
        </div>
        {edge && routeSource && routeTarget && (
          <NetworkRoutePanel
            source={routeSource}
            target={routeTarget}
            relation={edge.relation}
            decision={edge.decision}
            onClose={() => setEdgeId(null)}
            onSelect={(target) => selectNode(target.id)}
          />
        )}
        {!edge && node && (
          <NetworkConnectionPanel
            key={node.id}
            node={node}
            topology={topology}
            issues={nodeIssues.map((issue) => t(`issueText.${issue}`))}
            onSelect={(target) => selectNode(target.id)}
            onClose={() => onSelectNode(null)}
            onFocus={(agentId) => setPathOf(agentId)}
            loadPolicy={loadPolicy}
          />
        )}
        {peopleOpen && !edge && !node && (
          <NetworkPeoplePanel
            data={people.data}
            status={people.status}
            error={people.error}
            selectedId={personId}
            topology={topology}
            onSelect={selectPerson}
            onAgentSelect={(agent) => selectNode(agent.id)}
            onClose={() => {
              setPeopleOpen(false);
              setPersonId(null);
            }}
            onRetry={people.reload}
          />
        )}
      </div>
    </div>
  );
}

function Legend({ swatch, children }: { swatch: string; children: ReactNode }) {
  return (
    <span className="flex items-center gap-1.5">
      <span
        aria-hidden="true"
        className={cn("inline-block shrink-0", swatch)}
      />
      {children}
    </span>
  );
}
