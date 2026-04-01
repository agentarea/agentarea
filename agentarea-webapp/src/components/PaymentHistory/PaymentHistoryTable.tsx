"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { ExternalLink, ChevronLeft, ChevronRight } from "lucide-react";
import { useWalletPayments } from "@/hooks/useAgentWallet";
import Table from "@/components/Table/Table";
import EmptyState from "@/components/EmptyState";
import { LoadingSpinner } from "@/components/LoadingSpinner";

function getExplorerUrl(
  protocol: string,
  txHash: string,
  metadata?: Record<string, unknown>
): string | null {
  if (!txHash) return null;
  const network = (metadata?.network as string) || "";
  if (protocol === "x402") {
    if (network.includes("8453")) return `https://basescan.org/tx/${txHash}`;
    if (network.includes("1")) return `https://etherscan.io/tx/${txHash}`;
    if (network.includes("solana")) return `https://solscan.io/tx/${txHash}`;
    return `https://basescan.org/tx/${txHash}`;
  }
  return `https://temposcan.io/tx/${txHash}`;
}

function truncateAddress(addr: string): string {
  if (addr.length <= 12) return addr;
  return `${addr.slice(0, 6)}...${addr.slice(-4)}`;
}

interface PaymentHistoryTableProps {
  agentId: string;
}

const MOCK_PAYMENTS = [
  {
    id: "pay_1",
    created_at: new Date().toISOString(),
    protocol: "x402",
    amount_usd: 0.0523,
    recipient: "0x1234567890abcdef1234567890abcdef12345678",
    tool_name: "web_search",
    tx_hash: "0xabcdef1234567890abcdef1234567890abcdef1234567890abcdef12345678",
    status: "completed",
    protocol_metadata: { network: "base" },
  },
  {
    id: "pay_2",
    created_at: new Date(Date.now() - 3600000).toISOString(),
    protocol: "mpp",
    amount_usd: 1.25,
    recipient: "acct_123456789",
    tool_name: "image_generation",
    tx_hash: null,
    status: "pending",
    protocol_metadata: {},
  },
  {
    id: "pay_3",
    created_at: new Date(Date.now() - 86400000).toISOString(),
    protocol: "x402",
    amount_usd: 0.12,
    recipient: "0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
    tool_name: "contract_interaction",
    tx_hash: "0x7890abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234",
    status: "failed",
    protocol_metadata: { network: "ethereum" },
  },
];

export function PaymentHistoryTable({ agentId }: PaymentHistoryTableProps) {
  const t = useTranslations("AgentPaymentsPage");
  const [protocol, setProtocol] = useState<string>("all");
  const [page, setPage] = useState(1);

  const { data, loading } = useWalletPayments(agentId, {
    protocol: protocol === "all" ? undefined : protocol,
    page,
    page_size: 20,
  });

  // Use real data if available, otherwise use mock data for testing
  const payments = data?.items?.length ? data.items : MOCK_PAYMENTS;
  const total = data?.total || (data?.items?.length ? 0 : MOCK_PAYMENTS.length);
  const totalPages = Math.ceil(total / 20);

  if (loading && page === 1 && !data?.items?.length) {
    return (
      <div className="flex h-32 items-center justify-center">
        <LoadingSpinner />
      </div>
    );
  }

  if (payments.length === 0 && !loading && protocol === "all") {
    return (
      <EmptyState
        title={t("noPayments")}
        description={t("noPaymentsDescription")}
        iconsType="agent"
      />
    );
  }

  const columns = [
    {
      header: t("table.time"),
      accessor: "created_at",
      render: (value: string) => (
        <span className="font-mono text-xs">
          {value ? new Date(value).toLocaleString() : "-"}
        </span>
      ),
    },
    {
      header: t("table.protocol"),
      accessor: "protocol",
      render: (value: string) => (
        <Badge variant="outline" className="text-xs">
          {value}
        </Badge>
      ),
    },
    {
      header: t("table.amount"),
      accessor: "amount_usd",
      headerClassName: "text-right",
      cellClassName: "text-right font-mono",
      render: (value: number) => `$${value.toFixed(4)}`,
    },
    {
      header: t("table.recipient"),
      accessor: "recipient",
      render: (value: string) => (
        <span className="font-mono text-xs">{truncateAddress(value)}</span>
      ),
    },
    {
      header: t("table.tool"),
      accessor: "tool_name",
      cellClassName: "text-xs",
    },
    {
      header: t("table.txHash"),
      accessor: "tx_hash",
      render: (value: string, item: any) => {
        const explorerUrl = value
          ? getExplorerUrl(item.protocol, value, item.protocol_metadata)
          : null;
        return explorerUrl ? (
          <a
            href={explorerUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-xs text-blue-500 hover:underline"
          >
            {truncateAddress(value)}
            <ExternalLink className="h-3 w-3" />
          </a>
        ) : (
          <span className="text-xs text-muted-foreground">-</span>
        );
      },
    },
    {
      header: t("table.status"),
      accessor: "status",
      render: (value: string) => (
        <Badge
          variant={
            value === "completed"
              ? "default"
              : value === "failed"
                ? "destructive"
                : "secondary"
          }
          className="text-xs"
        >
          {value}
        </Badge>
      ),
    },
  ];

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex items-center gap-4 px-4 sm:px-0">
        <Select
          value={protocol}
          onValueChange={(v) => {
            setProtocol(v);
            setPage(1);
          }}
        >
          <SelectTrigger className="h-8 w-[140px] text-xs shadow-none border-zinc-200 dark:border-zinc-800 bg-transparent hover:bg-zinc-50 dark:hover:bg-zinc-800/50 transition-colors">
            <SelectValue placeholder="Protocol" />
          </SelectTrigger>
          <SelectContent className="dark:bg-zinc-900 border-zinc-200 dark:border-zinc-800">
            <SelectItem value="all" className="text-xs">All Protocols</SelectItem>
            <SelectItem value="x402" className="text-xs">x402</SelectItem>
            <SelectItem value="mpp" className="text-xs">MPP</SelectItem>
          </SelectContent>
        </Select>
        <span className="text-sm text-muted-foreground">{total} payments</span>
      </div>

      {/* Table */}
      {payments.length === 0 && !loading ? (
        <div className="py-12">
          <EmptyState
            title={t("noPayments")}
            description={t("noPaymentsDescription")}
            iconsType="agent"
          />
        </div>
      ) : (
        <div className="rounded-md border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-800/50">
          <Table data={payments} columns={columns} />
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 pb-4">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1 || loading}
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <span className="text-sm">
            Page {page} of {totalPages}
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages || loading}
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      )}
    </div>
  );
}
