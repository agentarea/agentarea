"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  Activity,
  Bot,
  Box,
  CircleDot,
  RefreshCw,
  Route,
  ShieldCheck,
  Zap,
} from "lucide-react";
import { AnimatedTabs } from "@/components/ui/animated-tabs";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import NodeDetailDrawer from "./components/NodeDetailDrawer";
import { useNetwork } from "./NetworkProvider";
import type { NetworkNodeData, TopologyResponse } from "./types";
import AccessGraphView from "./views/AccessGraphView";
import CytoscapeTopologyView from "./views/CytoscapeTopologyView";
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
      <span className="hidden font-mono text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground md:inline">
        Lens
      </span>
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
        <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
      </Button>
    </div>
  );
}

export default function NetworkClient() {
  const { topology, loading, view } = useNetwork();
  const [selectedNode, setSelectedNode] = useState<NetworkNodeData | null>(
    null
  );

  const handleSelect = (node: NetworkNodeData | null) => {
    setSelectedNode(node);
  };

  if (loading && !topology) {
    return <NetworkGraphSkeleton />;
  }

  if (!topology || topology.nodes.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center bg-[#f4f7fb] px-6 text-center dark:bg-zinc-950">
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl border border-dashed border-blue-300 bg-white text-blue-600 shadow-sm dark:border-blue-800 dark:bg-zinc-900 dark:text-blue-300">
          <Route className="h-6 w-6" />
        </div>
        <p className="mt-4 text-sm font-semibold text-foreground">
          Your topology starts with an agent
        </p>
        <p className="mt-1 max-w-sm text-xs leading-5 text-muted-foreground">
          Add an agent, trigger, or external connection. Relationships will
          appear here automatically as a live network map.
        </p>
      </div>
    );
  }

  const highlightId = selectedNode?.id ?? null;

  return (
    <div className="flex h-full min-h-0 w-full flex-col bg-[#f4f7fb] dark:bg-zinc-950">
      <div className="relative min-h-0 flex-1">
        {view === "access" ? (
          <AccessGraphView
            topology={topology}
            onNodeClick={handleSelect}
            highlightId={highlightId}
            onPaneClick={() => handleSelect(null)}
          />
        ) : view === "org" ? (
          <OrgChartView
            topology={topology}
            onNodeClick={handleSelect}
            highlightId={highlightId}
            onPaneClick={() => handleSelect(null)}
          />
        ) : (
          <CytoscapeTopologyView
            topology={topology}
            onNodeClick={handleSelect}
            highlightId={highlightId}
            onPaneClick={() => handleSelect(null)}
          />
        )}

        {selectedNode && (
          <NodeDetailDrawer
            node={selectedNode}
            topology={topology}
            onClose={() => handleSelect(null)}
          />
        )}
      </div>
      <TopologyStatusBar topology={topology} />
    </div>
  );
}

function TopologyStatusBar({ topology }: { topology: TopologyResponse }) {
  const agents = topology.nodes.filter((node) => node.type === "agent").length;
  const triggers = topology.nodes.filter(
    (node) => node.type === "trigger"
  ).length;
  const capabilities = topology.nodes.length - agents - triggers;

  const stats = [
    { label: "Agents", value: agents, icon: Bot, tone: "text-[#4f67e8]" },
    { label: "Ingress", value: triggers, icon: Zap, tone: "text-[#d88916]" },
    {
      label: "Capabilities",
      value: capabilities,
      icon: Box,
      tone: "text-[#14886a]",
    },
    {
      label: "Routes",
      value: topology.edges.length,
      icon: Activity,
      tone: "text-slate-500",
    },
  ];

  return (
    <div className="flex h-11 shrink-0 items-center justify-between gap-4 overflow-x-auto border-t border-slate-200/80 bg-white px-3 text-[10px] dark:border-zinc-800 dark:bg-zinc-950 md:px-4">
      <div className="flex shrink-0 items-center gap-4">
        {stats.map(({ label, value, icon: Icon, tone }) => (
          <div
            key={label}
            className="flex items-center gap-1.5 text-muted-foreground"
          >
            <Icon className={`h-3.5 w-3.5 ${tone}`} />
            <span className="font-mono uppercase tracking-[0.12em]">
              {label}
            </span>
            <span className="font-mono font-semibold tabular-nums text-foreground">
              {value}
            </span>
          </div>
        ))}
      </div>
      <div className="flex shrink-0 items-center gap-2 font-mono uppercase tracking-[0.12em] text-muted-foreground">
        <CircleDot className="h-3 w-3 text-emerald-500" />
        Current topology
        <span className="h-3 w-px bg-border" />
        <ShieldCheck className="h-3.5 w-3.5 text-[#4f67e8]" />
        Governed
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
