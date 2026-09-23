"use client";

import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import Table, { type Column } from "@/components/Table/Table";
import { Badge } from "@/components/ui/badge";
import { SecretRowActions } from "./SecretRowActions";
import { useSecretTypeLabel } from "./useSecretTypeLabel";

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

/** Where each owning entity's page lives. */
const OWNER_HREFS: Record<string, (id: string) => string | null> = {
  provider_config: () => "/admin/provider-configs",
  mcp_instance: (id) => `/connections/${id}`,
  // Auth configs are edited inside the connection they belong to, so there is
  // no page of their own to link at.
  mcp_auth_config: () => null,
  openapi_connection: () => "/connections/openapi",
  trigger: (id) => `/triggers/${id}`,
  agent: (id) => `/agents/${id}`,
};

function BelongsTo({ secret }: { secret: Secret }) {
  const t = useTranslations("SecretsPage.table");
  const typeLabel = useSecretTypeLabel();
  const owner = secret.owner;

  if (!owner) {
    const used = secret.used_by ?? [];
    if (used.length === 0) {
      return <span className="text-muted-foreground">{t("notUsed")}</span>;
    }
    const kinds = new Set(used.map((c) => typeLabel(c.consumer_type)));
    return (
      <span>
        {used.length} × {Array.from(kinds).join(", ")}
      </span>
    );
  }

  const href = OWNER_HREFS[owner.type]?.(owner.id) ?? null;
  // A secret can outlive whatever created it; saying so beats inventing a name.
  const name = owner.name ?? t("deletedOwner");

  return (
    <span className="flex flex-wrap items-center gap-1.5">
      <span className="text-muted-foreground">{typeLabel(owner.type)}</span>
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

export function SecretsTable({ secrets }: { secrets: Secret[] }) {
  const t = useTranslations("SecretsPage.table");
  const typeLabel = useSecretTypeLabel();
  const locale = useLocale();

  const columns: Column<Secret>[] = [
    {
      header: t("name"),
      accessor: "name",
      render: (_, row) =>
        !row ? null : row.owner ? (
          // The stored name is synthesised from the owner's id and reads as
          // noise; the slot it fills is what identifies it to a human, and the
          // next column says which connection it belongs to.
          <span className="flex items-center gap-2">
            <span>{row.owner.field ?? typeLabel(row.owner.type)}</span>
            <Badge variant="light" size="sm">
              {t("managed")}
            </Badge>
          </span>
        ) : (
          <span>{row.name}</span>
        ),
    },
    {
      header: t("description"),
      accessor: "description",
      render: (value) => (value as string | null) || "—",
    },
    {
      header: t("belongsTo"),
      accessor: "owner",
      render: (_, row) => (row ? <BelongsTo secret={row} /> : null),
    },
    {
      header: t("updated"),
      accessor: "updated_at",
      headerClassName: "w-[120px]",
      cellClassName: "whitespace-nowrap text-xs text-muted-foreground",
      render: (value) =>
        value
          ? new Date(value as string).toLocaleDateString(locale, {
              day: "2-digit",
              month: "short",
              year: "numeric",
            })
          : "—",
    },
    {
      header: "",
      accessor: "actions",
      headerClassName: "w-0",
      cellClassName: "text-right",
      // Managed secrets are changed through the connection that owns them, so
      // they get no actions here.
      render: (_, row) =>
        row && !row.owner ? <SecretRowActions secret={row} /> : null,
    },
  ];

  return <Table data={secrets} columns={columns} />;
}
