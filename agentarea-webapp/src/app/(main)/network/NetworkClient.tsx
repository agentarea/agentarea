"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { RefreshCw } from "lucide-react";
import { AnimatedTabs } from "@/components/ui/animated-tabs";
import { Button } from "@/components/ui/button";
import NetworkLegend from "./components/NetworkLegend";
import NetworkMetricsPanel from "./components/NetworkMetricsPanel";
import NodeDetailDrawer from "./components/NodeDetailDrawer";
import { useNetwork } from "./NetworkProvider";
import DataFlowView from "./views/DataFlowView";
import OrgChartView from "./views/OrgChartView";

interface NetworkNodeData {
  id: string;
  type: "agent" | "mcp_instance" | "openapi_connection" | "skill" | "trigger";
  label: string;
  status?: string | null;
  metadata: Record<string, any>;
}

export function NetworkHeaderTabs() {
  const { loading, fetchTopology } = useNetwork();
  const t = useTranslations("NetworkPage");
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();
  const view = searchParams.get("view") || "dataflow";

  const setView = (newView: string) => {
    const params = new URLSearchParams(searchParams);
    params.set("view", newView);
    router.replace(`${pathname}?${params.toString()}`);
  };

  return (
    <div className="inline-flex items-center gap-3 py-2">
      <AnimatedTabs
        tabs={[
          { value: "dataflow", label: t("dataFlow") },
          { value: "org", label: t("organization") },
        ]}
        activeTab={view}
        onChange={setView}
        size="sm"
        className="w-auto"
      />
      <div className="h-5 w-px bg-zinc-200 dark:bg-zinc-700" />
      <Button
        variant="ghost"
        size="sm"
        onClick={fetchTopology}
        disabled={loading}
        className="h-8 text-xs text-muted-foreground"
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
    return (
      <div className="flex h-full items-center justify-center">
        <RefreshCw className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!topology || topology.nodes.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-muted-foreground">
        <p className="text-sm font-medium">No entities found</p>
        <p className="text-xs">
          Create agents, skills, or connections to see the network.
        </p>
      </div>
    );
  }

  const highlightId = selectedNode?.id ?? null;

  return (
    <div className="relative h-full w-full">
      {view === "dataflow" ? (
        <DataFlowView
          topology={topology}
          onNodeClick={handleSelect}
          highlightId={highlightId}
          onPaneClick={() => handleSelect(null)}
        />
      ) : (
        <OrgChartView
          topology={topology}
          onNodeClick={handleSelect}
          highlightId={highlightId}
          onPaneClick={() => handleSelect(null)}
        />
      )}

      <NetworkLegend />
      <NetworkMetricsPanel topology={topology} />

      {selectedNode && topology && (
        <NodeDetailDrawer
          node={selectedNode}
          topology={topology}
          onClose={() => handleSelect(null)}
        />
      )}
    </div>
  );
}
