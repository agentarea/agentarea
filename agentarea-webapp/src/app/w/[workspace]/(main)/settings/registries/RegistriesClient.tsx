"use client";

import { useState, useTransition } from "react";
import { useTranslations } from "next-intl";
import {
  FolderGit2,
  Library,
  Link2,
  Package,
  Pencil,
  RefreshCw,
  Trash2,
} from "lucide-react";
import type { RegistryResponse } from "@/api/client/types.gen";
import BaseModal from "@/components/BaseModal";
import EmptyState from "@/components/EmptyState";
import FormError from "@/components/FormError";
import type { SelectableSecret } from "@/components/SecretSelect";
import Table, { type Column } from "@/components/Table/Table";
import { TableRowAction } from "@/components/Table/TableRowAction";
import { useViewerCapabilities } from "@/components/ViewerCapabilities";
import { deleteRegistryAction, syncRegistryAction } from "./actions";
import { describeRegistrySource, registryToForm } from "./registry-form";
import RegistryFormDialog, {
  type RegistryDialogTarget,
} from "./RegistryFormDialog";
import { RegistrySection, useRegistryColumns } from "./RegistryTableParts";

type Notice = { tone: "error" | "info"; message: string } | null;

function RowActions({
  registry,
  onEdit,
  onNotice,
}: {
  registry: RegistryResponse;
  onEdit: () => void;
  onNotice: (notice: Notice) => void;
}) {
  const t = useTranslations("Registries");
  const [syncing, startSync] = useTransition();

  const sync = () => {
    onNotice(null);
    startSync(async () => {
      const result = await syncRegistryAction(registry.id);
      onNotice(
        result.ok
          ? {
              tone: "info",
              message: t("syncDone", {
                name: registry.name,
                total: result.data.total,
                added: result.data.new_specs,
              }),
            }
          : { tone: "error", message: result.message }
      );
    });
  };

  const remove = async () => {
    const result = await deleteRegistryAction(registry.id);
    if (!result.ok) {
      onNotice({ tone: "error", message: result.message });
      return;
    }
    onNotice(
      result.data.status === "retired"
        ? {
            tone: "info",
            message: t("retired", {
              name: registry.name,
              count: result.data.kept_items,
            }),
          }
        : null
    );
  };

  return (
    <div className="flex items-center justify-end gap-1">
      <TableRowAction
        icon={<RefreshCw className={syncing ? "animate-spin" : undefined} />}
        onClick={sync}
        disabled={syncing || !registry.is_active}
      >
        {t("actions.sync")}
      </TableRowAction>
      <TableRowAction icon={<Pencil />} onClick={onEdit}>
        {t("actions.edit")}
      </TableRowAction>
      <BaseModal
        type="delete"
        title={t("delete.title")}
        description={t("delete.description", { name: registry.name })}
        onConfirm={remove}
      >
        <TableRowAction variant="destructiveOutline" icon={<Trash2 />}>
          {t("actions.delete")}
        </TableRowAction>
      </BaseModal>
    </div>
  );
}

/** The workspace's own registries; admins add, edit, sync and remove them. */
export default function RegistriesClient({
  registries,
  secrets,
}: {
  registries: RegistryResponse[];
  secrets: Promise<SelectableSecret[]>;
}) {
  const t = useTranslations("Registries");
  const { canAdminister } = useViewerCapabilities();
  const [dialog, setDialog] = useState<{
    target: RegistryDialogTarget;
    session: number;
  } | null>(null);
  const [notice, setNotice] = useState<Notice>(null);

  const openDialog = (target: RegistryDialogTarget) =>
    setDialog((previous) => ({
      target,
      session: (previous?.session ?? 0) + 1,
    }));

  const shared = useRegistryColumns<RegistryResponse>();
  const columns: Column<RegistryResponse>[] = [
    shared.name,
    {
      header: t("table.source"),
      accessor: "source_url",
      cellClassName: "max-w-[280px]",
      render: (_, registry) =>
        registry ? (
          <span className="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
            {registry.source_type === "github" ? (
              <FolderGit2 aria-hidden className="h-3.5 w-3.5 shrink-0" />
            ) : (
              <Link2 aria-hidden className="h-3.5 w-3.5 shrink-0" />
            )}
            <span className="truncate font-mono">
              {describeRegistrySource(registry)}
            </span>
          </span>
        ) : null,
    },
    shared.type,
    shared.trust,
    shared.items,
    shared.sync,
    ...(canAdminister
      ? [
          {
            header: "",
            accessor: "actions",
            headerClassName: "w-0",
            cellClassName: "text-right",
            render: (_: unknown, registry?: RegistryResponse) =>
              registry ? (
                <RowActions
                  registry={registry}
                  onNotice={setNotice}
                  onEdit={() =>
                    openDialog({
                      mode: "edit",
                      registryId: registry.id,
                      values: registryToForm(registry),
                    })
                  }
                />
              ) : null,
          } satisfies Column<RegistryResponse>,
        ]
      : []),
  ];

  return (
    <RegistrySection
      title={t("workspaceSection.title")}
      description={t("workspaceSection.description")}
    >
      {!canAdminister && (
        <p className="mb-3 text-xs text-muted-foreground">{t("adminOnly")}</p>
      )}
      {notice?.tone === "error" && (
        <FormError className="mb-3">{notice.message}</FormError>
      )}
      {notice?.tone === "info" && (
        <p role="status" className="mb-3 text-sm text-muted-foreground">
          {notice.message}
        </p>
      )}
      {registries.length === 0 ? (
        <EmptyState
          title={t("empty.title")}
          description={t("empty.description")}
          hints={[
            { text: t("empty.hintGithub") },
            { text: t("empty.hintIndex") },
            { text: t("empty.hintPolicy"), href: "/policies" },
          ]}
          icons={[FolderGit2, Library, Package]}
          action={
            canAdminister
              ? {
                  label: t("add"),
                  onClick: () => openDialog({ mode: "create" }),
                }
              : undefined
          }
        />
      ) : (
        <Table data={registries} columns={columns} />
      )}

      {dialog && (
        <RegistryFormDialog
          key={dialog.session}
          target={dialog.target}
          secrets={secrets}
          open
          onOpenChange={(open) => {
            if (!open) setDialog(null);
          }}
        />
      )}
    </RegistrySection>
  );
}
