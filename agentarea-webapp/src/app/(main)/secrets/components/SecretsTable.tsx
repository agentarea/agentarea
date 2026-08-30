"use client";

import Table from "@/components/Table/Table";
import { SecretRowActions } from "./SecretRowActions";

export type SecretConsumer = {
  consumer_type: string;
  consumer_id: string;
  field: string;
};

export type Secret = {
  id: string;
  name: string;
  description?: string | null;
  updated_at?: string | null;
  used_by?: SecretConsumer[];
};

const CONSUMER_LABELS: Record<string, string> = {
  provider_config: "LLM provider",
  openapi_connection: "API connection",
  mcp_instance: "MCP connection",
};

function describeUsage(used_by: SecretConsumer[] | undefined) {
  if (!used_by || used_by.length === 0) return "Not used yet";
  const kinds = new Set(
    used_by.map((c) => CONSUMER_LABELS[c.consumer_type] ?? c.consumer_type)
  );
  return `${used_by.length} × ${Array.from(kinds).join(", ")}`;
}

const columns = [
  { header: "Name", accessor: "name" },
  {
    header: "Description",
    accessor: "description",
    render: (value: string | null) => value || "—",
  },
  {
    header: "Used by",
    accessor: "used_by",
    render: (value: SecretConsumer[] | undefined) => describeUsage(value),
  },
  {
    header: "Updated",
    accessor: "updated_at",
    render: (value: string | null) =>
      value
        ? new Date(value).toLocaleDateString("en-US", {
            year: "numeric",
            month: "short",
            day: "numeric",
          })
        : "—",
  },
  {
    header: "",
    accessor: "id",
    render: (_value: string, row: Secret) => <SecretRowActions secret={row} />,
  },
];

export function SecretsTable({ secrets }: { secrets: Secret[] }) {
  return <Table data={secrets} columns={columns} />;
}
