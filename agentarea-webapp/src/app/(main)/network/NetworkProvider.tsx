"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { useSearchParams } from "next/navigation";
import { getNetworkTopologyAction as getNetworkTopology } from "@/lib/server-actions";

interface NetworkNodeData {
  id: string;
  type: "agent" | "mcp_instance" | "openapi_connection" | "skill" | "trigger";
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

interface NetworkContextValue {
  topology: TopologyResponse | null;
  loading: boolean;
  fetchTopology: () => Promise<void>;
  view: string;
}

const NetworkContext = createContext<NetworkContextValue | null>(null);

export function useNetwork() {
  const ctx = useContext(NetworkContext);
  if (!ctx) {
    throw new Error("useNetwork must be used within NetworkProvider");
  }
  return ctx;
}

export function NetworkProvider({ children }: { children: ReactNode }) {
  const searchParams = useSearchParams();
  const view = searchParams.get("view") || "dataflow";

  const [topology, setTopology] = useState<TopologyResponse | null>(null);
  const [loading, setLoading] = useState(true);

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

  return (
    <NetworkContext.Provider value={{ topology, loading, fetchTopology, view }}>
      {children}
    </NetworkContext.Provider>
  );
}
