"use client";

import { useCallback, useState } from "react";
import { useTranslations } from "next-intl";
import type { PaymentRecordResponse } from "@/api/client/types.gen";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  Copy,
  ExternalLink,
} from "lucide-react";
import EmptyState from "@/components/EmptyState";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import Table from "@/components/Table/Table";
import { TableDateDisplay } from "@/components/Table/TableDateDisplay";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { useWalletPayments } from "@/hooks/useAgentWallet";
import { getPaymentStatusPresentation } from "@/lib/status";

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
  if (!addr || addr.length <= 12) return addr || "-";
  return `${addr.slice(0, 6)}...${addr.slice(-4)}`;
}

function formatAmount(value: number): string {
  if (value >= 1) {
    return `$${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }
  return `$${value.toFixed(4)}`;
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [text]);

  return (
    <button
      onClick={handleCopy}
      className="ml-2 inline-flex h-6 w-6 items-center justify-center rounded-md hover:bg-muted transition-colors"
      title={copied ? "Copied!" : "Copy to clipboard"}
    >
      {copied ? (
        <Check className="h-3 w-3 text-green-500" />
      ) : (
        <Copy className="h-3 w-3 text-muted-foreground" />
      )}
    </button>
  );
}

interface PaymentHistoryTableProps {
  agentId: string;
}

export function PaymentHistoryTable({ agentId }: PaymentHistoryTableProps) {
  const t = useTranslations("AgentPaymentsPage");
  const [page, setPage] = useState(1);

  const { data, loading } = useWalletPayments(agentId, {
    page,
    page_size: 20,
  });

  const payments = data?.items || [];
  const total = data?.total || 0;
  const totalPages = Math.ceil(total / 20);

  if (loading && page === 1 && !data?.items?.length) {
    return (
      <div className="flex h-32 items-center justify-center">
        <LoadingSpinner />
      </div>
    );
  }

  if (payments.length === 0 && !loading) {
    return (
      <EmptyState
        title={t("noPayments")}
        description={t("noPaymentsDescription")}
        iconsType="payments"
      />
    );
  }

  const columns = [
    {
      header: t("table.time"),
      accessor: "created_at",
      cellClassName: "text-muted-foreground",
      render: (value: string) => <TableDateDisplay dateString={value} />,
    },
    {
      header: t("table.protocol"),
      accessor: "protocol",
      render: (value: string) => (
        <Badge
          variant="outline"
          className="text-xs font-medium border-primary/30 bg-primary/5"
        >
          {value.toUpperCase()}
        </Badge>
      ),
    },
    {
      header: t("table.amount"),
      accessor: "amount_usd",
      headerClassName: "text-right",
      cellClassName: "text-right",
      render: (value: number) => (
        <span className="font-semibold text-foreground">
          {formatAmount(value)}
        </span>
      ),
    },
    {
      header: t("table.recipient"),
      accessor: "recipient",
      render: (value: string, _item: PaymentRecordResponse) => (
        <div className="flex items-center">
          <span className="font-mono text-xs text-foreground">
            {truncateAddress(value)}
          </span>
          <CopyButton text={value} />
        </div>
      ),
    },
    {
      header: t("table.tool"),
      accessor: "tool_name",
      render: (value: string) => (
        <span className="text-sm text-muted-foreground">{value || "-"}</span>
      ),
    },
    {
      header: t("table.txHash"),
      accessor: "tx_hash",
      render: (value: string, item: PaymentRecordResponse) => {
        const explorerUrl = value
          ? getExplorerUrl(item.protocol, value, item.protocol_metadata ?? undefined)
          : null;
        return explorerUrl ? (
          <div className="flex items-center">
            <a
              href={explorerUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-xs text-primary hover:underline font-mono"
            >
              {truncateAddress(value)}
              <ExternalLink className="h-3 w-3" />
            </a>
            <CopyButton text={value} />
          </div>
        ) : (
          <span className="text-xs text-muted-foreground">-</span>
        );
      },
    },
    {
      header: t("table.status"),
      accessor: "status",
      render: (value: string) => {
        const status = getPaymentStatusPresentation(value);

        return (
          <StatusIndicator
            size="sm"
            tone={status.tone}
            pulse={status.pulse}
            className="whitespace-nowrap"
          >
            {status.label}
          </StatusIndicator>
        );
      },
    },
  ];

  return (
    <div className="space-y-4">
      {/* Table */}
      {payments.length === 0 && !loading ? (
        <div className="py-12">
          <EmptyState
            title={t("noPayments")}
            description={t("noPaymentsDescription")}
            iconsType="payments"
          />
        </div>
      ) : (
        <Table data={payments} columns={columns} />
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
