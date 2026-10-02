"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { RefreshCw, Route } from "lucide-react";
import { AnimatedTabs } from "@/components/ui/animated-tabs";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  getNetworkPeopleAccessAction,
  previewNetworkPolicyAction,
} from "./actions";
import { useNetwork } from "./NetworkProvider";
import type { NetworkNodeData } from "./types";
import { findFocusedNode } from "./utils/focusNode";
import NetworkGraphView from "./views/NetworkGraphView";

export function NetworkHeaderTabs() {
  const t = useTranslations("NetworkPage.graph.lenses");
  const searchParams = useSearchParams();
  const { view } = useNetwork();

  // A lens is client state mirrored into the URL. history.replaceState keeps
  // useSearchParams in sync without a server round trip, so the graph starts
  // moving on the click rather than after a refetch.
  const setView = (newView: string) => {
    const params = new URLSearchParams(searchParams);
    params.set("view", newView);
    window.history.replaceState(null, "", `?${params.toString()}`);
  };

  return (
    <div className="flex min-w-0 items-center gap-3 py-1.5">
      <AnimatedTabs
        tabs={[
          { value: "overview", label: t("overview.tab") },
          { value: "delegation", label: t("delegation.tab") },
          { value: "access", label: t("access.tab") },
        ]}
        activeTab={view}
        onChange={setView}
        size="sm"
        className="w-auto"
      />
    </div>
  );
}

export function NetworkHeaderControls() {
  const { loading, fetchTopology } = useNetwork();

  return (
    <div className="flex items-center gap-2">
      <Button
        variant="ghost"
        size="icon"
        onClick={fetchTopology}
        disabled={loading}
        className="h-7 w-7 text-muted-foreground"
        aria-label="Refresh topology"
      >
        <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
      </Button>
    </div>
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
      <div
        className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center"
        role="alert"
      >
        <p className="text-sm font-medium">{t("loadError")}</p>
        <Button
          size="sm"
          variant="outline"
          onClick={fetchTopology}
          disabled={loading}
        >
          {t("retry")}
        </Button>
      </div>
    );
  }

  if (!topology || topology.nodes.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center bg-layoutBackground px-6 text-center">
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl border border-dashed border-primary/40 bg-background text-primary shadow-sm">
          <Route className="h-6 w-6" />
        </div>
        <p className="mt-4 text-sm font-semibold text-foreground">
          {t("emptyTitle")}
        </p>
        <p className="mt-1 max-w-sm text-xs leading-5 text-muted-foreground">
          {t("emptyDescription")}
        </p>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 w-full flex-col">
      {error && (
        <div
          className="flex shrink-0 items-center justify-between gap-3 border-b border-border bg-background px-4 py-2 text-xs"
          role="alert"
        >
          <span>{t("refreshError")}</span>
          <Button
            size="xs"
            variant="ghost"
            onClick={fetchTopology}
            disabled={loading}
          >
            {t("retry")}
          </Button>
        </div>
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
function NetworkGraphSkeleton() {
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
