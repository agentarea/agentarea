"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { Check, Network, Users } from "lucide-react";
import DisplayMenu from "@/components/DisplayMenu";
import EmptyState from "@/components/EmptyState";
import HeaderTabs from "@/components/HeaderTabs";
import NoticeBanner from "@/components/NoticeBanner";
import SearchInput from "@/components/SearchInput";
import SubheaderToolbar from "@/components/SubheaderToolbar";
import ToolbarRefreshButton from "@/components/ToolbarRefreshButton";
import { Button } from "@/components/ui/button";
import { CountSegmentedControl } from "@/components/ui/count-segmented-control";
import { MenuRow, MenuSectionLabel } from "@/components/ui/menu-row";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { ToolbarButton } from "@/components/ui/toolbar";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import {
  getNetworkPeopleAccessAction,
  previewNetworkPolicyAction,
} from "./actions";
import { useNetwork, type NetworkMode } from "./NetworkProvider";
import type { NetworkNodeData } from "./types";
import { findFocusedNode } from "./utils/focusNode";
import { buildNetworkGraph, issueCount } from "./utils/networkGraph";
import NetworkGraphView from "./views/NetworkGraphView";

export function NetworkToolbar() {
  const t = useTranslations("NetworkPage.graph");
  const lenses = useTranslations("NetworkPage.graph.lenses");
  const peopleText = useTranslations("NetworkPage.people");
  const searchParams = useSearchParams();
  const {
    topology,
    view,
    mode,
    setMode,
    query,
    setQuery,
    showIssues,
    setShowIssues,
    showPeople,
    setShowPeople,
    loading,
    fetchTopology,
  } = useNetwork();
  const issues = useMemo(
    () => (topology ? issueCount(buildNetworkGraph(topology)) : 0),
    [topology]
  );
  const peopleLens = view !== "access" && view !== "flow";

  // A lens is client state mirrored into the URL. history.replaceState keeps
  // useSearchParams in sync without a server round trip, so the graph starts
  // moving on the click rather than after a refetch.
  const setView = (newView: string) => {
    const params = new URLSearchParams(searchParams);
    params.set("view", newView);
    window.history.replaceState(null, "", `?${params.toString()}`);
  };

  return (
    <SubheaderToolbar
      categories={
        <CountSegmentedControl
          items={(["overview", "delegation", "access", "flow"] as const).map(
            (value) => ({ value, label: lenses(`${value}.tab`) })
          )}
          value={view}
          onChange={setView}
          variant="solid"
          className="max-w-full"
          layoutId="network-lens-control"
        />
      }
      search={
        <SearchInput
          delay={150}
          initialValue={query}
          placeholder={t("search")}
          onDebouncedChange={setQuery}
        />
      }
      controls={
        <>
          <ToolbarButton
            active={showIssues}
            aria-pressed={showIssues}
            disabled={issues === 0}
            onClick={() => setShowIssues(!showIssues)}
          >
            <StatusIndicator
              kind={issues > 0 ? "attention" : "done"}
              aria-hidden
            />
            {t("issues")}
            <span className="tabular-nums text-muted-foreground">{issues}</span>
          </ToolbarButton>
          <HeaderTabs
            tabs={[
              {
                value: "graph",
                label: t("modes.graph"),
                icon: <Network className="h-4 w-4" />,
              },
              { value: "list", label: t("modes.list") },
            ]}
            value={mode}
            onChange={(next) => setMode(next as NetworkMode)}
          />
          {peopleLens && (
            <DisplayMenu>
              <MenuSectionLabel>{t("show")}</MenuSectionLabel>
              <MenuRow
                icon={<Users className="h-3.5 w-3.5" />}
                label={peopleText("title")}
                selected={showPeople}
                onClick={() => setShowPeople(!showPeople)}
                trailing={
                  showPeople ? <Check className="h-3.5 w-3.5" /> : undefined
                }
              />
            </DisplayMenu>
          )}
          <ToolbarRefreshButton
            onRefresh={fetchTopology}
            refreshing={loading}
          />
        </>
      }
    />
  );
}

export default function NetworkClient() {
  const { topology, loading, error, fetchTopology, view } = useNetwork();
  const t = useTranslations("NetworkPage.integration");
  const searchParams = useSearchParams();
  const focus = searchParams.get("focus");
  const [selectedNode, setSelectedNode] = useState<NetworkNodeData | null>(
    null
  );
  // Applied once per focus value: the graph opens on what the caller pointed
  // at, and closing the panel has to stay closed rather than snapping back.
  const appliedFocus = useRef<string | null>(null);

  useEffect(() => {
    if (!topology || appliedFocus.current === focus) return;
    appliedFocus.current = focus;
    setSelectedNode(findFocusedNode(topology.nodes, focus));
  }, [topology, focus]);

  if (loading && !topology) {
    return <NetworkGraphSkeleton />;
  }

  if (error && !topology) {
    return (
      <EmptyState
        title={t("loadError")}
        icons={[Network]}
        action={{ label: t("retry"), onClick: fetchTopology }}
      />
    );
  }

  if (!topology || topology.nodes.length === 0) {
    return (
      <EmptyState
        title={t("emptyTitle")}
        description={t("emptyDescription")}
        icons={[ENTITY_ICONS.agent, ENTITY_ICONS.mcp, ENTITY_ICONS.trigger]}
        action={{ label: t("emptyAction"), href: "/agents" }}
      />
    );
  }

  return (
    <div className="flex h-full min-h-0 w-full flex-col">
      {error && (
        <NoticeBanner
          title={t("refreshError")}
          className="m-3 mb-0 shrink-0"
          action={
            <Button
              size="xs"
              variant="outline"
              onClick={fetchTopology}
              disabled={loading}
            >
              {t("retry")}
            </Button>
          }
        />
      )}
      <div className="relative min-h-0 flex-1">
        <NetworkGraphView
          lens={view}
          topology={topology}
          loadPeopleAccess={getNetworkPeopleAccessAction}
          loadPolicy={previewNetworkPolicyAction}
          selectedNodeId={selectedNode?.id ?? null}
          onSelectNode={setSelectedNode}
        />
      </div>
    </div>
  );
}

// Placeholder for the graph canvas — scattered node bubbles while the topology
// loads. The header tabs stay mounted above (page subheader).
export function NetworkGraphSkeleton() {
  const nodes = [
    { top: "30%", left: "22%" },
    { top: "18%", left: "55%" },
    { top: "52%", left: "38%" },
    { top: "42%", left: "72%" },
    { top: "72%", left: "58%" },
    { top: "62%", left: "20%" },
  ];
  return (
    <div
      className="relative h-full w-full bg-layoutBackground"
      aria-hidden="true"
    >
      {nodes.map((n, i) => (
        <div
          key={i}
          className="absolute flex -translate-x-1/2 -translate-y-1/2 flex-col items-center gap-2"
          style={{ top: n.top, left: n.left }}
        >
          <Skeleton className="h-12 w-12 rounded-full" />
          <Skeleton className="h-2.5 w-14" />
        </div>
      ))}
    </div>
  );
}
