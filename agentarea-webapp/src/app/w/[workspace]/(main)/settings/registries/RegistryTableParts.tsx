"use client";

import type { ReactNode } from "react";
import { useLocale, useTranslations } from "next-intl";
import { formatDistanceToNow } from "date-fns";
import { ru } from "date-fns/locale";
import { SettingsSectionHeading } from "@/app/w/[workspace]/(main)/settings/components/SettingsSection";
import { RegistryBadge } from "@/components/RegistryBadge";
import type { Column } from "@/components/Table/Table";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { getRegistrySyncStatusPresentation } from "@/lib/status";
import type { RegistryRow } from "./registry-rows";

function SyncCell({ registry }: { registry: RegistryRow }) {
  const t = useTranslations("Registries");
  const locale = useLocale();
  const presentation = getRegistrySyncStatusPresentation(registry);
  const when = registry.last_synced_at
    ? formatDistanceToNow(new Date(registry.last_synced_at), {
        addSuffix: true,
        locale: locale === "ru" ? ru : undefined,
      })
    : null;

  return (
    <div className="min-w-0 space-y-0.5">
      <StatusIndicator kind={presentation.kind} size="sm">
        {t(`sync.${presentation.labelKey}`)}
        {when && presentation.kind !== "failed" ? ` · ${when}` : ""}
      </StatusIndicator>
      {registry.last_sync_error && (
        <p
          className="max-w-[260px] truncate text-xs text-red-600 dark:text-red-400"
          title={registry.last_sync_error}
        >
          {registry.last_sync_error}
        </p>
      )}
    </div>
  );
}

/** The columns both sections of the page share, by name, for each to arrange. */
export function useRegistryColumns<T extends RegistryRow>() {
  const t = useTranslations("Registries");

  const name: Column<T> = {
    header: t("table.name"),
    accessor: "name",
    cellClassName: "max-w-[260px]",
    render: (_, registry) =>
      registry ? (
        <div className="min-w-0">
          <span className="block truncate text-[13px] font-medium">
            {registry.name}
          </span>
          {registry.description && (
            <span className="block truncate text-xs text-muted-foreground">
              {registry.description}
            </span>
          )}
        </div>
      ) : null,
  };

  const type: Column<T> = {
    header: t("table.type"),
    accessor: "registry_type",
    headerClassName: "w-[130px]",
    cellClassName: "whitespace-nowrap text-xs text-muted-foreground",
    render: (value, registry) => (
      <div className="space-y-0.5">
        <span className="block">
          {t.has(`types.${String(value)}`)
            ? t(`types.${String(value)}`)
            : String(value)}
        </span>
        {registry && (
          <span className="block">{t(`modes.${registry.mode}`)}</span>
        )}
      </div>
    ),
  };

  const trust: Column<T> = {
    header: t("table.trust"),
    accessor: "trust",
    headerClassName: "w-[120px]",
    render: (_, registry) =>
      registry ? <RegistryBadge trust={registry.trust} /> : null,
  };

  const items: Column<T> = {
    header: t("table.items"),
    accessor: "item_count",
    headerClassName: "w-[70px] text-right",
    cellClassName: "text-right tabular-nums text-xs",
    render: (value) => String(value),
  };

  const sync: Column<T> = {
    header: t("table.sync"),
    accessor: "last_synced_at",
    headerClassName: "w-[200px]",
    render: (_, registry) =>
      registry ? <SyncCell registry={registry} /> : null,
  };

  return { name, type, trust, items, sync };
}

/** One section of the page: a heading and its lead above the section's table. */
export function RegistrySection({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <section className="space-y-2.5">
      <SettingsSectionHeading title={title} description={description} />
      {children}
    </section>
  );
}
