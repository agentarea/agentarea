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
import { zGetNetworkTopologyV1NetworkTopologyGetResponse } from "@/api/client/zod.gen";
import { getNetworkTopologyAction as getNetworkTopology } from "@/lib/server-actions";
import type { TopologyResponse } from "./types";

interface NetworkContextValue {
  topology: TopologyResponse | null;
  loading: boolean;
  error: boolean;
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
  const requestedView = searchParams.get("view");
  const view =
    requestedView === "dataflow" ? "topology" : requestedView || "topology";

  const [topology, setTopology] = useState<TopologyResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const fetchTopology = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const { data, error } = await getNetworkTopology();
      if (error || !data) {
        setError(true);
        return;
      }
      const parsed =
        zGetNetworkTopologyV1NetworkTopologyGetResponse.parse(data);
      setTopology({
        ...parsed,
        nodes: parsed.nodes.map((node) => ({
          ...node,
          metadata: node.metadata ?? {},
        })),
      });
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTopology();
  }, [fetchTopology]);

  return (
    <NetworkContext.Provider
      value={{ topology, loading, error, fetchTopology, view }}
    >
      {children}
    </NetworkContext.Provider>
  );
}
