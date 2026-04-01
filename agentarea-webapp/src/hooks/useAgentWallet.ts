"use client";

import { useState, useEffect, useCallback } from "react";
import {
  getAgentWalletAction,
  createAgentWalletAction,
  updateAgentWalletAction,
  deleteAgentWalletAction,
  getAgentWalletPaymentsAction,
} from "@/lib/server-actions";

export interface AgentWallet {
  id: string;
  agent_id: string;
  wallet_type: "x402" | "mpp" | "dual";
  x402_config?: {
    network: string;
    facilitator_url: string;
    scheme: string;
    signer_type: string;
  };
  mpp_config?: {
    payment_method_types: string[];
    session_budget_usd: number;
    stripe_profile_id?: string;
  };
  has_credentials: boolean;
  service_budget_usd: number;
  service_budget_period: "execution" | "daily" | "monthly";
  status: string;
  created_at?: string;
  updated_at?: string;
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

function isAgentWallet(value: unknown): value is AgentWallet {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.id === "string" &&
    typeof v.agent_id === "string" &&
    typeof v.wallet_type === "string" &&
    typeof v.has_credentials === "boolean" &&
    typeof v.service_budget_usd === "number" &&
    typeof v.service_budget_period === "string" &&
    typeof v.status === "string"
  );
}

function isPaginatedPayments(value: unknown): value is PaginatedPayments {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return (
    Array.isArray(v.items) &&
    typeof v.total === "number" &&
    typeof v.page === "number" &&
    typeof v.page_size === "number"
  );
}

export function useAgentWallet(agentId: string) {
  const [wallet, setWallet] = useState<AgentWallet | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchWallet = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const { data, error: err } = await getAgentWalletAction(agentId);
      if (err) {
        setWallet(null);
      } else {
        setWallet(isAgentWallet(data) ? data : null);
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

  const createWallet = async (data: Record<string, unknown>): Promise<AgentWallet> => {
    setLoading(true);
    try {
      const { data: result, error } = await createAgentWalletAction(agentId, data as any);
      if (error) throw new Error("Failed to create wallet");
      if (!isAgentWallet(result)) throw new Error("Invalid wallet response");
      return result;
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
      const { data: result, error } = await updateAgentWalletAction(agentId, data as any);
      if (error) throw new Error("Failed to update wallet");
      if (!isAgentWallet(result)) throw new Error("Invalid wallet response");
      return result;
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
      await deleteAgentWalletAction(agentId);
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
      const { data: result } = await getAgentWalletPaymentsAction(agentId, filters);
      if (isPaginatedPayments(result)) {
        setData(result);
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
