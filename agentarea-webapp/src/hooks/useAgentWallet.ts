"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import type { CreateWalletRequest } from "@/api/client/types.gen";
import { apiErrorMessage, formatApiError } from "@/lib/api-errors";
import {
  createAgentWalletAction,
  deleteAgentWalletAction,
  getAgentWalletAction,
  getAgentWalletPaymentsAction,
  updateAgentWalletAction,
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
    session_budget_usd: string | number;
    stripe_profile_id?: string;
  };
  has_credentials: boolean;
  service_budget_usd: string;
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
  amount_usd: string;
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
    typeof v.service_budget_usd === "string" &&
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
  const t = useTranslations("AgentWallet.errors");
  const [wallet, setWallet] = useState<AgentWallet | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchWallet = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const result = await getAgentWalletAction(agentId);
      if (result.status === 404) {
        setWallet(null);
      } else if (result.error) {
        setWallet(null);
        setError(apiErrorMessage(result, t("fetchWallet")));
      } else if (!isAgentWallet(result.data)) {
        setWallet(null);
        setError(t("invalidWallet"));
      } else {
        setWallet(result.data);
      }
    } catch (err) {
      console.error("Failed to fetch wallet", err);
      setError(t("fetchWallet"));
    } finally {
      setLoading(false);
    }
  }, [agentId, t]);

  useEffect(() => {
    fetchWallet();
  }, [fetchWallet]);

  return { wallet, loading, error, refetch: fetchWallet };
}

export function useCreateWallet(agentId: string) {
  const t = useTranslations("AgentWallet.errors");
  const [loading, setLoading] = useState(false);

  const createWallet = async (
    data: CreateWalletRequest
  ): Promise<AgentWallet> => {
    setLoading(true);
    try {
      const { data: result, error } = await createAgentWalletAction(
        agentId,
        data
      );
      if (error) {
        throw new Error(`${t("createWallet")}: ${formatApiError(error)}`);
      }
      if (!isAgentWallet(result)) throw new Error(t("invalidWallet"));
      return result;
    } finally {
      setLoading(false);
    }
  };

  return { createWallet, loading };
}

export function useUpdateWallet(agentId: string) {
  const t = useTranslations("AgentWallet.errors");
  const [loading, setLoading] = useState(false);

  const updateWallet = async (
    data: Record<string, unknown>
  ): Promise<AgentWallet> => {
    setLoading(true);
    try {
      const { data: result, error } = await updateAgentWalletAction(
        agentId,
        data
      );
      if (error) {
        throw new Error(`${t("updateWallet")}: ${formatApiError(error)}`);
      }
      if (!isAgentWallet(result)) throw new Error(t("invalidWallet"));
      return result;
    } finally {
      setLoading(false);
    }
  };

  return { updateWallet, loading };
}

export function useDeleteWallet(agentId: string) {
  const t = useTranslations("AgentWallet.errors");
  const [loading, setLoading] = useState(false);

  const deleteWallet = async (): Promise<void> => {
    setLoading(true);
    try {
      const { error } = await deleteAgentWalletAction(agentId);
      if (error) {
        throw new Error(`${t("removeWallet")}: ${formatApiError(error)}`);
      }
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
  const t = useTranslations("AgentWallet.errors");
  const [data, setData] = useState<PaginatedPayments | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const protocol = filters?.protocol;
  const status = filters?.status;
  const page = filters?.page;
  const page_size = filters?.page_size;

  const fetchPayments = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const result = await getAgentWalletPaymentsAction(agentId, {
        protocol,
        status,
        page,
        page_size,
      });
      if (result.error) {
        setError(apiErrorMessage(result, t("fetchPayments")));
      } else if (!isPaginatedPayments(result.data)) {
        setError(t("invalidPayments"));
      } else {
        setData(result.data);
      }
    } catch (err) {
      console.error("Failed to fetch payments", err);
      setError(t("fetchPayments"));
    } finally {
      setLoading(false);
    }
  }, [agentId, protocol, status, page, page_size, t]);

  useEffect(() => {
    fetchPayments();
  }, [fetchPayments]);

  return { data, loading, error, refetch: fetchPayments };
}
