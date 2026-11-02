"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Globe, KeyRound, Pencil, Trash2, Waypoints } from "lucide-react";
import type { EgressExitResponse } from "@/api/client/types.gen";
import BaseModal from "@/components/BaseModal";
import EmptyState from "@/components/EmptyState";
import FormError from "@/components/FormError";
import Table, { type Column } from "@/components/Table/Table";
import { TableRowAction } from "@/components/Table/TableRowAction";
import { deleteEgressExitAction } from "./actions";
import { egressExitToForm } from "./egress-exit-form";
import EgressExitFormDialog, {
  type EgressExitDialogTarget,
  type SecretChoices,
} from "./EgressExitFormDialog";

const isPlatform = (exit: EgressExitResponse) => exit.managed_by === "platform";

function RowActions({
  exit,
  onEdit,
  onError,
}: {
  exit: EgressExitResponse;
  onEdit: () => void;
  onError: (message: string | null) => void;
}) {
  const t = useTranslations("EgressExits");

  const remove = async () => {
    onError(null);
    const result = await deleteEgressExitAction(exit.id);
    if (!result.ok) onError(result.message);
  };

  return (
    <div className="flex items-center justify-end gap-1">
      <TableRowAction icon={<Pencil />} onClick={onEdit}>
        {t("actions.edit")}
      </TableRowAction>
      <BaseModal
        type="delete"
        title={t("delete.title")}
        description={t("delete.description", { name: exit.name })}
        onConfirm={remove}
      >
        <TableRowAction variant="destructiveOutline" icon={<Trash2 />}>
          {t("actions.delete")}
        </TableRowAction>
      </BaseModal>
    </div>
  );
}

/**
 * The workspace's own exits, which members add, edit and remove, followed by
 * the platform's, which can be bound but are the operator's to change.
 */
export default function EgressExitsClient({
  exits,
  secrets,
}: {
  exits: EgressExitResponse[];
  secrets: Promise<SecretChoices>;
}) {
  const t = useTranslations("EgressExits");
  const [dialog, setDialog] = useState<{
    target: EgressExitDialogTarget;
    session: number;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const openDialog = (target: EgressExitDialogTarget) =>
    setDialog((previous) => ({
      target,
      session: (previous?.session ?? 0) + 1,
    }));

  const rows = [
    ...exits.filter((exit) => !isPlatform(exit)),
    ...exits.filter(isPlatform),
  ];

  const columns: Column<EgressExitResponse>[] = [
    {
      header: t("table.name"),
      accessor: "name",
      cellClassName: "max-w-[280px]",
      render: (_, exit) =>
        exit ? (
          <div className="min-w-0">
            <span className="block truncate text-[13px] font-medium">
              {exit.name}
            </span>
            {isPlatform(exit) && (
              <span className="block text-xs text-muted-foreground">
                {t("platformLabel")}
              </span>
            )}
            {exit.description && (
              <span className="block truncate text-xs text-muted-foreground">
                {exit.description}
              </span>
            )}
          </div>
        ) : null,
    },
    {
      header: t("table.proxy"),
      accessor: "upstream_url",
      cellClassName: "max-w-[280px]",
      render: (_, exit) =>
        exit ? (
          <span className="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
            <Globe aria-hidden className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate font-mono">
              {exit.upstream_url ?? t("viaHop", { via: exit.via ?? "" })}
            </span>
          </span>
        ) : null,
    },
    {
      header: t("table.credentials"),
      accessor: "username",
      headerClassName: "w-[200px]",
      render: (_, exit) =>
        exit?.username ? (
          <span className="flex min-w-0 items-center gap-1.5 text-xs">
            <span className="truncate font-mono">{exit.username}</span>
            {exit.password_secret_id && (
              <KeyRound
                aria-label={t("passwordFromSecret")}
                className="h-3.5 w-3.5 shrink-0 text-muted-foreground"
              />
            )}
          </span>
        ) : (
          <span className="text-xs text-muted-foreground">
            {t("noCredentials")}
          </span>
        ),
    },
    {
      header: "",
      accessor: "actions",
      headerClassName: "w-0",
      cellClassName: "text-right",
      render: (_, exit) =>
        exit && !isPlatform(exit) ? (
          <RowActions
            exit={exit}
            onError={setError}
            onEdit={() =>
              openDialog({
                mode: "edit",
                exitId: exit.id,
                values: egressExitToForm(exit),
              })
            }
          />
        ) : null,
    },
  ];

  return (
    <div className="space-y-3">
      {error && <FormError>{error}</FormError>}
      {rows.length === 0 ? (
        <EmptyState
          title={t("empty.title")}
          description={t("empty.description")}
          icons={[Waypoints, Globe, KeyRound]}
          action={{
            label: t("add"),
            onClick: () => openDialog({ mode: "create" }),
          }}
        />
      ) : (
        <Table data={rows} columns={columns} />
      )}

      {dialog && (
        <EgressExitFormDialog
          key={dialog.session}
          target={dialog.target}
          secrets={secrets}
          open
          onOpenChange={(open) => {
            if (!open) setDialog(null);
          }}
        />
      )}
    </div>
  );
}
