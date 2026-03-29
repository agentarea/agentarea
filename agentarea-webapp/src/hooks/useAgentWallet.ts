"use client";

import { useState, useEffect, useCallback } from "react";
import browserClient from "@/lib/browser-client";

interface X402Config {
  network: string;
  facilitator_url: string;
  scheme: string;
  signer_type: string;
}

interface MPPConfig {
  payment_method_types: string[];
  session_budget_usd: number;
  stripe_profile_id?: string;
}

interface WalletCredentials {
  x402_private_key?: string;
  mpp_tempo_key?: string;
}

export interface AgentWallet {
  id: string;
  agent_id: string;
  wallet_type: "x402" | "mpp" | "dual";
  x402_config?: X402Config;
  mpp_config?: MPPConfig;
  has_credentials: boolean;
  service_budget_usd: number;
  service_budget_period: "execution" | "daily" | "monthly";
  status: string;
  created_at?: string;
  updated_at?: string;
}

export interface WalletBalance {
  service_budget_usd: number;
  service_budget_period: string;
  total_spent_current_period: number;
  remaining: number;
}

export interface PaymentRecord {
  id: string;
  agent_id: string;
  execution_id: string;
  protocol: "x402" | "mpp";
  amount_usd: number;
  recipient: string;
  tx_hash?: string;
  tool_name: string;
  tool_call_id: string;
  status: "completed" | "failed" | "pending";
  error_message?: string;
  protocol_metadata?: Record<string, unknown>;
  created_at?: string;
}

export interface PaginatedPayments {
  items: PaymentRecord[];
  total: number;
  page: number;
  page_size: number;
}

export function useAgentWallet(agentId: string) {
  const [wallet, setWallet] = useState<AgentWallet | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchWallet = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await browserClient.GET("/v1/agents/{agent_id}/wallet" as any, {
        params: { path: { agent_id: agentId } },
      } as any);
      if ((response as any).error) {
        if ((response as any).response?.status === 404) {
          setWallet(null);
        } else {
          setError("Failed to fetch wallet");
        }
      } else {
        setWallet((response as any).data as AgentWallet);
      }
    } catch {
      setError("Failed to fetch wallet");
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    fetchWallet();
  }, [fetchWallet]);

  return { wallet, loading, error, refetch: fetchWallet };
}

export function useCreateWallet(agentId: string) {
  const [loading, setLoading] = useState(false);

  const createWallet = async (data: {
    wallet_type: string;
    x402_config?: X402Config;
    mpp_config?: MPPConfig;
    credentials?: WalletCredentials;
    service_budget_usd: number;
    service_budget_period: string;
  }): Promise<AgentWallet> => {
    setLoading(true);
    try {
      const response = await browserClient.POST("/v1/agents/{agent_id}/wallet" as any, {
        params: { path: { agent_id: agentId } },
        body: data as any,
      } as any);
      if ((response as any).error) throw new Error("Failed to create wallet");
      return (response as any).data as AgentWallet;
    } finally {
      setLoading(false);
    }
  };

  return { createWallet, loading };
}

export function useUpdateWallet(agentId: string) {
  const [loading, setLoading] = useState(false);

  const updateWallet = async (data: Record<string, unknown>): Promise<AgentWallet> => {
    setLoading(true);
    try {
      const response = await browserClient.PUT("/v1/agents/{agent_id}/wallet" as any, {
        params: { path: { agent_id: agentId } },
        body: data as any,
      } as any);
      if ((response as any).error) throw new Error("Failed to update wallet");
      return (response as any).data as AgentWallet;
    } finally {
      setLoading(false);
    }
  };

  return { updateWallet, loading };
}

export function useDeleteWallet(agentId: string) {
  const [loading, setLoading] = useState(false);

  const deleteWallet = async (): Promise<void> => {
    setLoading(true);
    try {
      await browserClient.DELETE("/v1/agents/{agent_id}/wallet" as any, {
        params: { path: { agent_id: agentId } },
      } as any);
    } finally {
      setLoading(false);
    }
  };

  return { deleteWallet, loading };
}

export function useWalletPayments(
  agentId: string,
  filters?: {
    protocol?: string;
    status?: string;
    page?: number;
    page_size?: number;
  }
) {
  const [data, setData] = useState<PaginatedPayments | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchPayments = useCallback(async () => {
    try {
      setLoading(true);
      const response = await browserClient.GET(
        "/v1/agents/{agent_id}/wallet/payments" as any,
        {
          params: {
            path: { agent_id: agentId },
            query: filters as any,
          },
        } as any
      );
      if (!(response as any).error) {
        setData((response as any).data as PaginatedPayments);
      }
    } finally {
      setLoading(false);
    }
  }, [agentId, filters?.protocol, filters?.status, filters?.page, filters?.page_size]);

  useEffect(() => {
    fetchPayments();
  }, [fetchPayments]);

  return { data, loading, refetch: fetchPayments };
}
