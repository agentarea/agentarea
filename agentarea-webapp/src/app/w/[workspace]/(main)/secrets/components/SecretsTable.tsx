"use client";

import { useTranslations } from "next-intl";
import Link from "@/components/WorkspaceLink";
import { KeyRound, Lock } from "lucide-react";
import Table, { type Column } from "@/components/Table/Table";
import { TableDateDisplay } from "@/components/Table/TableDateDisplay";
import { EntityAvatar } from "@/components/ui/entity-avatar";
import { deterministicHue } from "@/lib/avatar-hue";
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
  provider_config: () => "/models",
  mcp_instance: (id) => `/connections/${id}`,
  // Auth configs are edited inside the connection they belong to, so there is
  // no page of their own to link at.
  mcp_auth_config: () => null,
  openapi_connection: () => "/connections/openapi",
  trigger: (id) => `/triggers/${id}`,
  agent: (id) => `/agents/${id}`,
};

/** Two-line cell for the owning/consuming entity. */
function CellLines({
  primary,
  secondary,
}: {
  primary: React.ReactNode;
  secondary?: React.ReactNode;
}) {
  return (
    <span className="flex min-w-0 flex-col gap-0.5 text-xs">
      <span className="flex min-w-0 items-center gap-2">{primary}</span>
      {secondary ? (
        <span className="truncate text-xs text-muted-foreground">
          {secondary}
        </span>
      ) : null}
    </span>
  );
}

function SecretCell({ secret }: { secret: Secret }) {
  const typeLabel = useSecretTypeLabel();
  const owner = secret.owner;

  return (
    <span className="flex min-w-0 items-center gap-2">
      <EntityAvatar
        aria-hidden
        size={20}
        hue={deterministicHue(secret.id)}
        // Managed secrets are changed where they belong, so they read as locked.
        icon={
          owner ? <Lock strokeWidth={1.85} /> : <KeyRound strokeWidth={1.85} />
        }
      />
      <span className="truncate font-medium">
        {/* The stored name of a managed secret is synthesised from the owner's
            id and reads as noise; the slot it fills identifies it to a human. */}
        {owner ? (owner.field ?? typeLabel(owner.type)) : secret.name}
      </span>
      {/* No "Managed" badge here. It was set on every secret that had an
          owner, so a token you pasted in yourself came back labelled as
          something the platform provisioned — and it only ever repeated what
          the "Used by" column already spells out. */}
    </span>
  );
}

function UsedByCell({ secret }: { secret: Secret }) {
  const t = useTranslations("SecretsPage.table");
  const typeLabel = useSecretTypeLabel();
  const owner = secret.owner;

  if (owner) {
    const href = OWNER_HREFS[owner.type]?.(owner.id) ?? null;
    return (
      <CellLines
        primary={
          // A secret can outlive whatever created it; saying so beats
          // inventing a name.
          !owner.name ? (
            <span className="text-muted-foreground">{t("deletedOwner")}</span>
          ) : href ? (
            <Link
              href={href}
              className="truncate underline-offset-2 hover:text-primary hover:underline"
            >
              {owner.name}
            </Link>
          ) : (
            <span className="truncate">{owner.name}</span>
          )
        }
        secondary={typeLabel(owner.type)}
      />
    );
  }

  const used = secret.used_by ?? [];
  if (used.length === 0) {
    return (
      <span className="text-xs text-muted-foreground">{t("notUsed")}</span>
    );
  }

  const kinds = Array.from(
    new Set(used.map((c) => typeLabel(c.consumer_type)))
  );
  return (
    <CellLines
      primary={<span className="truncate">{kinds.join(", ")}</span>}
      secondary={t("places", { count: used.length })}
    />
  );
}

export function SecretsTable({ secrets }: { secrets: Secret[] }) {
  const t = useTranslations("SecretsPage.table");

  const columns: Column<Secret>[] = [
    {
      header: t("name"),
      accessor: "name",
      render: (_, row) => (row ? <SecretCell secret={row} /> : null),
    },
    {
      header: t("description"),
      accessor: "description",
      cellClassName: "max-w-[300px]",
      render: (value) => (
        <span className="block truncate text-xs text-muted-foreground">
          {(value as string | null | undefined) || "-"}
        </span>
      ),
    },
    {
      header: t("usedBy"),
      accessor: "owner",
      headerClassName: "w-[30%]",
      render: (_, row) => (row ? <UsedByCell secret={row} /> : null),
    },
    {
      header: t("updated"),
      accessor: "updated_at",
      headerClassName: "w-[150px]",
      cellClassName: "whitespace-nowrap",
      render: (value) => (
        <TableDateDisplay
          dateString={(value as string | null | undefined) ?? ""}
          onlyDate
        />
      ),
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
