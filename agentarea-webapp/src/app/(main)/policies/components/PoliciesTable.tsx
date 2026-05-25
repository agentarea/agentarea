"use client";

import { Badge } from "@/components/ui/badge";
import Table from "@/components/Table/Table";

type Policy = {
  id: string;
  scope_type: string;
  scope_id: string;
  enabled: boolean;
  document: Record<string, unknown>;
};

function docSummary(document: Record<string, unknown>): string {
  const type = document?.type ?? document?.kind ?? document?.policy_type;
  if (type) return String(type);
  const keys = Object.keys(document ?? {});
  if (keys.length === 0) return "—";
  return keys.slice(0, 2).join(", ");
}

const columns = [
  {
    header: "Scope type",
    accessor: "scope_type",
  },
  {
    header: "Scope ID",
    accessor: "scope_id",
    render: (value: string) => (
      <span className="font-mono text-xs">{value}</span>
    ),
  },
  {
    header: "Enabled",
    accessor: "enabled",
    render: (value: boolean) => (
      <Badge variant={value ? "success" : "secondary"}>
        {value ? "enabled" : "disabled"}
      </Badge>
    ),
  },
  {
    header: "Document",
    accessor: "document",
    render: (value: Record<string, unknown>) => (
      <span className="text-xs text-muted-foreground">{docSummary(value)}</span>
    ),
  },
];

export function PoliciesTable({ policies }: { policies: Policy[] }) {
  return <Table data={policies} columns={columns} />;
}
