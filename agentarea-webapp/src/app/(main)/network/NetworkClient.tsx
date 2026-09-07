"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { CircleDot, RefreshCw, Route } from "lucide-react";
import { AnimatedTabs } from "@/components/ui/animated-tabs";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { previewNetworkPolicyAction } from "./actions";
import { useNetwork } from "./NetworkProvider";
import type { NetworkNodeData } from "./types";
import AccessGraphView from "./views/AccessGraphView";
import NetworkMapView from "./views/NetworkMapView";
import OrgChartView from "./views/OrgChartView";

export function NetworkHeaderTabs() {
  const t = useTranslations("NetworkPage");
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();
  const requestedView = searchParams.get("view");
  const view =
    requestedView === "dataflow" ? "topology" : requestedView || "topology";

  const setView = (newView: string) => {
    const params = new URLSearchParams(searchParams);
    params.set("view", newView);
    router.replace(`${pathname}?${params.toString()}`);
  };

  return (
    <div className="flex min-w-0 items-center gap-3 py-1.5">
      <AnimatedTabs
        tabs={[
          { value: "topology", label: t("topology") },
          { value: "access", label: t("accessGraph") },
          { value: "org", label: t("organization") },
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
  const { topology, loading, fetchTopology } = useNetwork();

  return (
    <div className="flex items-center gap-2">
      <div className="hidden items-center gap-2 rounded-full border border-emerald-200/80 bg-emerald-50/70 px-2.5 py-1 text-[10px] font-semibold text-emerald-700 dark:border-emerald-900/70 dark:bg-emerald-950/40 dark:text-emerald-300 sm:flex">
        <CircleDot className="h-3 w-3 text-emerald-500" />
        {topology ? `${topology.nodes.length} nodes mapped` : "Loading map"}
      </div>
      <Button
        variant="ghost"
        size="icon"
        onClick={fetchTopology}
        disabled={loading}
        className="h-7 w-7 text-muted-foreground"
        aria-label="Refresh topology"
      >
        <RefreshCw className={loading ? "animate-spin" : ""} />
      </Button>
    </div>
  );
}

export default function NetworkClient() {
  const { topology, loading, error, fetchTopology, view } = useNetwork();
  const t = useTranslations("NetworkPage.integration");
  const [selectedNode, setSelectedNode] = useState<NetworkNodeData | null>(
    null
  );

  const handleSelect = (node: NetworkNodeData | null) => {
    setSelectedNode(node);
  };

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
      <div className="flex h-full flex-col items-center justify-center bg-[#f4f7fb] px-6 text-center dark:bg-zinc-950">
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl border border-dashed border-blue-300 bg-white text-blue-600 shadow-sm dark:border-blue-800 dark:bg-zinc-900 dark:text-blue-300">
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

  const highlightId = selectedNode?.id ?? null;

  return (
    <div className="flex h-full min-h-0 w-full flex-col bg-[#f4f7fb] dark:bg-zinc-950">
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
        {view === "access" ? (
          <AccessGraphView
            topology={topology}
            loadPolicy={previewNetworkPolicyAction}
            onNodeClick={handleSelect}
            highlightId={highlightId}
            onPaneClick={() => handleSelect(null)}
          />
        ) : view === "org" ? (
          <OrgChartView
            topology={topology}
            loadPolicy={previewNetworkPolicyAction}
            onNodeClick={handleSelect}
            highlightId={highlightId}
            onPaneClick={() => handleSelect(null)}
          />
        ) : (
          <NetworkMapView
            topology={topology}
            loadPolicy={previewNetworkPolicyAction}
            onNodeClick={handleSelect}
            highlightId={highlightId}
            onPaneClick={() => handleSelect(null)}
          />
        )}
      </div>
    </div>
  );
}

// Placeholder for the topology canvas — scattered node bubbles while the graph
// data loads. The header tabs stay mounted above (page subheader).
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
      className="relative h-full w-full bg-[#f4f7fb] dark:bg-zinc-950"
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
