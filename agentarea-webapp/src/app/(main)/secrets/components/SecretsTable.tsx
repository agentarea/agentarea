"use client";

import Link from "next/link";
import { Brain, Globe, KeyRound, type LucideIcon } from "lucide-react";
import Table from "@/components/Table/Table";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import { SecretRowActions } from "./SecretRowActions";

export type SecretConsumer = {
  consumer_type: string;
  consumer_id: string;
  field: string;
};

export type SecretOwner = {
  type: string;
  id: string;
  name?: string | null;
  field?: string | null;
};

export type Secret = {
  id: string;
  name: string;
  description?: string | null;
  updated_at?: string | null;
  used_by?: SecretConsumer[];
  owner?: SecretOwner | null;
};

/** How each owning entity is labelled, drawn, and where its page lives. */
const OWNERS: Record<
  string,
  { label: string; icon: LucideIcon; href: (id: string) => string | null }
> = {
  provider_config: { label: "LLM provider", icon: Brain, href: () => "/models" },
  mcp_instance: {
    label: "MCP connection",
    icon: ENTITY_ICONS.mcp,
    href: (id) => `/connections/${id}`,
  },
  // Auth configs are edited inside the connection they belong to, so there is
  // no page of their own to link at.
  mcp_auth_config: {
    label: "MCP authentication",
    icon: KeyRound,
    href: () => null,
  },
  openapi_connection: {
    label: "API connection",
    icon: Globe,
    href: () => "/connections/openapi",
  },
  trigger: {
    label: "Trigger",
    icon: ENTITY_ICONS.trigger,
    href: (id) => `/triggers/${id}`,
  },
  agent: {
    label: "Agent wallet",
    icon: ENTITY_ICONS.agent,
    href: (id) => `/agents/${id}`,
  },
};

const CONSUMER_LABELS: Record<string, string> = {
  provider_config: "LLM provider",
  openapi_connection: "API connection",
  mcp_instance: "MCP connection",
};

function BelongsTo({ secret }: { secret: Secret }) {
  const owner = secret.owner;

  if (!owner) {
    const used = secret.used_by ?? [];
    if (used.length === 0) {
      return <span className="text-muted-foreground">Not used yet</span>;
    }
    const kinds = new Set(
      used.map((c) => CONSUMER_LABELS[c.consumer_type] ?? c.consumer_type)
    );
    return (
      <span>
        {used.length} × {Array.from(kinds).join(", ")}
      </span>
    );
  }

  const meta = OWNERS[owner.type];
  const href = meta?.href(owner.id) ?? null;
  // A secret can outlive whatever created it; saying so beats inventing a name.
  const name = owner.name ?? "deleted";
  const Icon = meta?.icon;

  return (
    <span className="flex flex-wrap items-center gap-1.5">
      {Icon && (
        <Icon aria-hidden="true" className="h-3.5 w-3.5 text-muted-foreground" />
      )}
      <span className="text-muted-foreground">{meta?.label ?? owner.type}</span>
      {href ? (
        <Link
          href={href}
          className="underline underline-offset-2 hover:text-foreground"
        >
          {name}
        </Link>
      ) : (
        <span>{name}</span>
      )}
    </span>
  );
}

const columns = [
  {
    header: "Name",
    accessor: "name",
    render: (_value: string, row: Secret) =>
      row.owner ? (
        // The stored name is synthesised from the owner's id and reads as
        // noise; the slot it fills is what identifies it to a human, and the
        // next column says which connection it belongs to.
        //
        // No "Managed" badge here. It was set on every secret that had an
        // owner, so a token you pasted in yourself came back labelled as
        // something the platform provisioned — and it only ever repeated what
        // the next column already spells out.
        <span className="flex items-center gap-2">
          <span>{row.owner.field ?? OWNERS[row.owner.type]?.label ?? row.name}</span>
        </span>
      ) : (
        <span>{row.name}</span>
      ),
  },
  {
    header: "Description",
    accessor: "description",
    render: (value: string | null) => value || "—",
  },
  {
    header: "Belongs to",
    accessor: "owner",
    render: (_value: unknown, row: Secret) => <BelongsTo secret={row} />,
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
    // Managed secrets are changed through the connection that owns them, so
    // they get no menu here.
    render: (_value: string, row: Secret) =>
      row.owner ? null : <SecretRowActions secret={row} />,
  },
];

export function SecretsTable({ secrets }: { secrets: Secret[] }) {
  return <Table data={secrets} columns={columns} />;
}
