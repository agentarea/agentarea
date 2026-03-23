"use client";

import { useTranslations } from "next-intl";
import { formatDistanceToNow } from "date-fns";
import Table from "@/components/Table/Table";
import { Badge } from "@/components/ui/badge";

interface ExecutionsTableProps {
  executions: any[];
  triggerId: string;
  currentPage: number;
}

function getStatusVariant(status: string) {
  switch (status) {
    case "completed":
    case "success":
      return "default" as const;
    case "failed":
    case "error":
      return "destructive" as const;
    case "running":
    case "in_progress":
      return "secondary" as const;
    default:
      return "outline" as const;
  }
}

export default function ExecutionsTable({
  executions,
  triggerId,
  currentPage,
}: ExecutionsTableProps) {
  const t = useTranslations("TriggersPage.detail");

  const columns = [
    {
      accessor: "id",
      header: "Execution ID",
      render: (value: string) => (
        <span className="font-mono text-xs">{value?.slice(0, 8)}...</span>
      ),
    },
    {
      accessor: "status",
      header: "Status",
      render: (value: string) => (
        <Badge variant={getStatusVariant(value)}>
          {value || "unknown"}
        </Badge>
      ),
    },
    {
      accessor: "started_at",
      header: "Started",
      render: (value: string) => (
        <span className="text-muted-foreground">
          {value
            ? formatDistanceToNow(new Date(value), { addSuffix: true })
            : "-"}
        </span>
      ),
    },
    {
      accessor: "duration_ms",
      header: "Duration",
      render: (value: number) => (
        <span className="text-muted-foreground">
          {value != null ? `${(value / 1000).toFixed(2)}s` : "-"}
        </span>
      ),
    },
    {
      accessor: "result",
      header: "Result",
      render: (value: any) => (
        <span className="max-w-xs truncate text-muted-foreground block text-xs">
          {value ? (typeof value === "string" ? value : JSON.stringify(value)) : "-"}
        </span>
      ),
    },
  ];

  return <Table data={executions} columns={columns} />;
}
