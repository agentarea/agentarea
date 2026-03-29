"use client";

import { useCallback, useEffect, useState } from "react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { RefreshCw } from "lucide-react";
import { getNetworkTopologyAction as getNetworkTopology } from "@/lib/server-actions";
import DataFlowView from "./views/DataFlowView";
import OrgChartView from "./views/OrgChartView";
import NodeDetailPanel from "./components/NodeDetailPanel";

interface NetworkNodeData {
  id: string;
  type: "agent" | "mcp_instance" | "skill" | "trigger";
  label: string;
  status?: string | null;
  metadata: Record<string, any>;
}

interface TopologyResponse {
  nodes: NetworkNodeData[];
  edges: { id: string; source: string; target: string; relation: string }[];
  governance: any[];
  deployment_mode: string;
}

export default function NetworkClient() {
  const [topology, setTopology] = useState<TopologyResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedNode, setSelectedNode] = useState<NetworkNodeData | null>(null);

  const fetchTopology = useCallback(async () => {
    setLoading(true);
    try {
      const { data, error } = await getNetworkTopology();
      if (error || !data) {
        console.error("Failed to fetch topology:", error);
        return;
      }
      setTopology(data as TopologyResponse);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTopology();
  }, [fetchTopology]);

  if (loading && !topology) {
    return (
      <div className="flex h-[calc(100vh-16rem)] items-center justify-center">
        <RefreshCw className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!topology || topology.nodes.length === 0) {
    return (
      <div className="flex h-[calc(100vh-16rem)] flex-col items-center justify-center gap-3 text-muted-foreground">
        <p className="text-sm font-medium">No entities found</p>
        <p className="text-xs">Create agents, skills, or connections to see the network.</p>
        <Button variant="outline" size="sm" onClick={fetchTopology}>
          <RefreshCw className="mr-2 h-3.5 w-3.5" />
          Refresh
        </Button>
      </div>
    );
  }

  return (
    <div className="relative w-full">
      <Tabs defaultValue="dataflow">
        <div className="flex items-center justify-between mb-4">
          <TabsList className="h-8">
            <TabsTrigger value="dataflow" className="text-xs px-3">Data Flow</TabsTrigger>
            <TabsTrigger value="org" className="text-xs px-3">Organization</TabsTrigger>
          </TabsList>
          <Button
            variant="ghost"
            size="sm"
            onClick={fetchTopology}
            disabled={loading}
            className="h-8 text-xs text-muted-foreground"
          >
            <RefreshCw className={`h-3.5 w-3.5 mr-1.5 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>

        <TabsContent value="dataflow" className="mt-0">
          <DataFlowView topology={topology} onNodeClick={setSelectedNode} />
        </TabsContent>

        <TabsContent value="org" className="mt-0">
          <OrgChartView topology={topology} onNodeClick={setSelectedNode} />
        </TabsContent>
      </Tabs>

      {selectedNode && (
        <NodeDetailPanel node={selectedNode} onClose={() => setSelectedNode(null)} />
      )}
    </div>
  );
}
