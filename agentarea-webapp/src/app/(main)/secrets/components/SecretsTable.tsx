"use client";

import { useRouter } from "next/navigation";
import Table from "@/components/Table/Table";

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
    render: (value: string | null) => value ?? "—",
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
      onRowClick={(item) => router.push(`/mcp-servers/${item.id}`)}
    />
  );
}
