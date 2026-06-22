"use client";

import { formatDistanceToNow } from "date-fns";
import Table from "@/components/Table/Table";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { getTriggerExecutionStatusPresentation } from "@/lib/status";

interface ExecutionsTableProps {
  executions: any[];
  triggerId: string;
  currentPage: number;
}

export default function ExecutionsTable({
  executions,
  triggerId,
  currentPage,
}: ExecutionsTableProps) {
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
      render: (value: string) => {
        const status = getTriggerExecutionStatusPresentation(value || "unknown");

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
    {
      accessor: "executed_at",
      header: "Executed",
      render: (value: string) => (
        <span className="text-muted-foreground">
          {value
            ? formatDistanceToNow(new Date(value), { addSuffix: true })
            : "-"}
        </span>
      ),
    },
    {
      accessor: "execution_time_ms",
      header: "Duration",
      render: (value: number) => (
        <span className="text-muted-foreground">
          {value != null ? `${value}ms` : "-"}
        </span>
      ),
    },
    {
      accessor: "task_id",
      header: "Task",
      render: (value: string) => (
        <span className="font-mono text-xs text-muted-foreground">
          {value ? `${value.slice(0, 8)}...` : "-"}
        </span>
      ),
    },
    {
      accessor: "error_message",
      header: "Error",
      render: (value: string) => (
        <span className="max-w-xs truncate text-muted-foreground block text-xs">
          {value || "-"}
        </span>
      ),
    },
  ];

  return <Table data={executions} columns={columns} />;
}
