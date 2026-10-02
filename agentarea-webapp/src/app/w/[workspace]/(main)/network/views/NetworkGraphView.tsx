"use client";

import { useCallback, useMemo, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { AlertTriangle, Search, Users, X } from "lucide-react";
import type {
  EffectivePolicy,
  NetworkPeopleAccessResponse,
} from "@/api/client/types.gen";
import { useViewerCapabilities } from "@/components/ViewerCapabilities";
import { cn } from "@/lib/utils";
import type { NetworkActionResult } from "../actions";
import NetworkCanvas from "../components/NetworkCanvas";
import NetworkSelectionList from "../components/NetworkSelectionList";
import NetworkConnectionPanel from "../components/NetworkConnectionPanel";
import NetworkPeoplePanel from "../components/NetworkPeoplePanel";
import NetworkRoutePanel from "../components/NetworkRoutePanel";
import type { NetworkNodeData, TopologyResponse } from "../types";
import { useNetworkPeople } from "../useNetworkPeople";
import {
  buildNetworkGraph,
  graphForLens,
  isResource,
  issueCount,
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

const chipClass =
  "flex h-9 items-center gap-1.5 rounded-md border border-border px-2.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary aria-pressed:border-primary/40 aria-pressed:bg-primary/5 aria-pressed:text-foreground";

export default function NetworkGraphView({
  lens,
  topology,
  loadPolicy,
  loadPeopleAccess,
  selectedNodeId,
  onSelectNode,
}: NetworkGraphViewProps) {
  const t = useTranslations("NetworkPage.graph");
  const types = useTranslations("NetworkPage.orgChart");
  const peopleText = useTranslations("NetworkPage.people");
  const accessText = useTranslations("NetworkPage.accessDetails");
  const { canAdminister } = useViewerCapabilities();
  const people = useNetworkPeople(canAdminister, loadPeopleAccess, topology);

  const [showPeople, setShowPeople] = useState(false);
  const [showIssues, setShowIssues] = useState(false);
  const [query, setQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
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
    setSearchOpen(false);
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

  const pickResult = (id: string) => {
    setQuery("");
    setSearchOpen(false);
    selectNode(id);
  };

  const togglePeople = () => {
    const next = !showPeople;
    setShowPeople(next);
    if (next && people.status !== "ready") setPeopleOpen(true);
    if (!next && personId) setPersonId(null);
  };

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
  const issues = issueCount(graph);

  return (
    <div className="flex h-full min-h-0 w-full flex-col bg-layoutBackground">
      <div className="relative z-10 flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-border bg-background px-4 py-3 md:px-5">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-foreground">
            {t(`lenses.${lens}.title`)}
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {t(`lenses.${lens}.description`)}
          </p>
        </div>
        {pathNode && (
          <button
            type="button"
            onClick={() => setPathOf(null)}
            className="flex max-w-full items-center gap-2 rounded-md border border-primary/20 bg-primary/5 px-2.5 py-1.5 text-xs text-primary"
            aria-label={accessText("clearFocus")}
          >
            <span className="truncate">
              {accessText("focusedOn", { name: pathNode.label })}
            </span>
            <X className="h-3.5 w-3.5 shrink-0" />
          </button>
        )}
        <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">
          {lens !== "access" && (
            <button
              type="button"
              aria-pressed={showPeople}
              onClick={togglePeople}
              className={chipClass}
            >
              <Users className="h-3.5 w-3.5" />
              {peopleText("title")}
            </button>
          )}
          <button
            type="button"
            aria-pressed={showIssues}
            onClick={() => setShowIssues((value) => !value)}
            className={chipClass}
          >
            <AlertTriangle
              className={cn("h-3.5 w-3.5", issues > 0 && "text-destructive")}
            />
            {t("issues")}
            <span className="tabular-nums">{issues}</span>
          </button>
          <div
            className="relative min-w-0 flex-1 sm:w-64"
            onBlur={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget))
                setSearchOpen(false);
            }}
          >
            <Search className="pointer-events-none absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
            <input
              aria-label={t("search")}
              placeholder={t("search")}
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
                if (event.key === "Enter" && results[0])
                  pickResult(results[0].id);
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
            {query.trim() && searchOpen && (
              <div className="absolute right-0 top-11 z-20 max-h-64 w-64 max-w-[calc(100vw-2rem)] overflow-auto rounded-lg border border-border bg-popover p-1 shadow-lg">
                <p
                  className="px-2 py-2 text-xs text-muted-foreground"
                  role="status"
                >
                  {t("matches", { count: results.length })}
                </p>
                {results.map((result) => (
                  <button
                    type="button"
                    key={result.id}
                    onClick={() => pickResult(result.id)}
                    className="block w-full rounded px-2 py-2 text-left text-xs hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                  >
                    <span className="block truncate font-medium">
                      {result.label}
                    </span>
                    <span className="mt-0.5 block text-muted-foreground">
                      {result.kind === "person"
                        ? peopleText("title")
                        : types(`types.${result.kind}`)}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {visible.nodes.length > 0 && (
        <NetworkSelectionList
          nodes={visible.nodes}
          edges={visible.edges}
          selectedId={canvasSelection}
          onSelectNode={selectNode}
          onSelectEdge={selectEdge}
        />
      )}
      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <div className="relative min-h-0 min-w-0 flex-1 overflow-hidden">
          {visible.nodes.length === 0 ? (
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

      <div className="flex shrink-0 flex-wrap items-center justify-between gap-x-4 gap-y-2 border-t border-border bg-background px-4 py-2.5 text-xs text-muted-foreground md:px-5">
        <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2 tabular-nums">
          <span>{t("counts.agents", { count: counts.agents })}</span>
          <span>{t("counts.resources", { count: counts.resources })}</span>
          <span>{t("counts.triggers", { count: counts.triggers })}</span>
          <span>{t("counts.links", { count: counts.links })}</span>
        </div>
        <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2">
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
        </div>
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
