"use client";

import { useRouter } from "next/navigation";
import Table from "@/components/Table/Table";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { getMcpCatalogStatusPresentation } from "@/lib/status";

type MCPInstance = {
  id: string;
  name: string;
  auth_type?: string | null;
  status?: string | null;
  created_at?: string | null;
};

const columns = [
  {
    header: "Connection name",
    accessor: "name",
  },
  {
    header: "Auth type",
    accessor: "auth_type",
    render: (value: string | null) => value ?? "None",
  },
  {
    header: "Status",
    accessor: "status",
    render: (value: string | null) => {
      if (!value) return "—";
      const status = getMcpCatalogStatusPresentation(value);
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
    header: "Created",
    accessor: "created_at",
    render: (value: string | null) => {
      if (!value) return "—";
      return new Date(value).toLocaleDateString("en-US", {
        year: "numeric",
        month: "short",
        day: "numeric",
      });
    },
  },
];

export function SecretsTable({ instances }: { instances: MCPInstance[] }) {
  const router = useRouter();
  return (
    <Table
      data={instances}
      columns={columns}
      onRowClick={(item) => router.push(`/connections/${item.id}`)}
    />
  );
}
