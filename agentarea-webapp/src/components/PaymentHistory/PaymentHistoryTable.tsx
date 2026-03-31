"use client";

import { useState } from "react";
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

export function PaymentHistoryTable({ agentId }: PaymentHistoryTableProps) {
  const [protocol, setProtocol] = useState<string>("all");
  const [page, setPage] = useState(1);

  const { data, loading } = useWalletPayments(agentId, {
    protocol: protocol === "all" ? undefined : protocol,
    page,
    page_size: 20,
  });

  const payments = data?.items || [];
  const total = data?.total || 0;
  const totalPages = Math.ceil(total / 20);

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex items-center gap-4">
        <Select
          value={protocol}
          onValueChange={(v) => {
            setProtocol(v);
            setPage(1);
          }}
        >
          <SelectTrigger className="w-[140px]">
            <SelectValue placeholder="Protocol" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Protocols</SelectItem>
            <SelectItem value="x402">x402</SelectItem>
            <SelectItem value="mpp">MPP</SelectItem>
          </SelectContent>
        </Select>
        <span className="text-sm text-muted-foreground">{total} payments</span>
      </div>

      {/* Table */}
      <div className="rounded-md border">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b bg-muted/50">
              <th className="p-3 text-left font-medium">Time</th>
              <th className="p-3 text-left font-medium">Protocol</th>
              <th className="p-3 text-right font-medium">Amount</th>
              <th className="p-3 text-left font-medium">Recipient</th>
              <th className="p-3 text-left font-medium">Tool</th>
              <th className="p-3 text-left font-medium">Tx Hash</th>
              <th className="p-3 text-left font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={7} className="p-6 text-center text-muted-foreground">
                  Loading...
                </td>
              </tr>
            ) : payments.length === 0 ? (
              <tr>
                <td colSpan={7} className="p-6 text-center text-muted-foreground">
                  No payments yet
                </td>
              </tr>
            ) : (
              payments.map((p) => {
                const explorerUrl = p.tx_hash
                  ? getExplorerUrl(p.protocol, p.tx_hash, p.protocol_metadata)
                  : null;
                return (
                  <tr key={p.id} className="border-b last:border-0">
                    <td className="p-3 font-mono text-xs">
                      {p.created_at ? new Date(p.created_at).toLocaleString() : "-"}
                    </td>
                    <td className="p-3">
                      <Badge variant="outline" className="text-xs">
                        {p.protocol}
                      </Badge>
                    </td>
                    <td className="p-3 text-right font-mono">${p.amount_usd.toFixed(4)}</td>
                    <td className="p-3 font-mono text-xs">{truncateAddress(p.recipient)}</td>
                    <td className="p-3 text-xs">{p.tool_name}</td>
                    <td className="p-3">
                      {explorerUrl ? (
                        <a
                          href={explorerUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 text-xs text-blue-500 hover:underline"
                        >
                          {p.tx_hash ? truncateAddress(p.tx_hash) : "-"}
                          <ExternalLink className="h-3 w-3" />
                        </a>
                      ) : (
                        <span className="text-xs text-muted-foreground">-</span>
                      )}
                    </td>
                    <td className="p-3">
                      <Badge
                        variant={
                          p.status === "completed"
                            ? "default"
                            : p.status === "failed"
                              ? "destructive"
                              : "secondary"
                        }
                        className="text-xs"
                      >
                        {p.status}
                      </Badge>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
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
            disabled={page >= totalPages}
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      )}
    </div>
  );
}
