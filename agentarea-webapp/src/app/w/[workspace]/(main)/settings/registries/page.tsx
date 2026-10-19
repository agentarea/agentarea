import { Suspense } from "react";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import type { SelectableSecret } from "@/components/SecretSelect";
import { TableSkeleton } from "@/components/Skeleton";
import { listSecrets } from "@/lib/api";
import { getViewerCapabilities } from "@/lib/workspace-context";
import AddRegistryButton from "./AddRegistryButton";
import RegistriesContent from "./RegistriesContent";

export const metadata: Metadata = {
  title: "Registries",
};

// The secrets a registry may read its source with, for the add/edit form. A
// failed load leaves the picker empty; the form still saves without one.
async function secretOptions(): Promise<SelectableSecret[]> {
  const result = await listSecrets();
  if (result.error) {
    console.error("Failed to load secrets for registries", result.error);
  }
  return (result.data ?? []).map(({ id, name }) => ({ id, name }));
}

export default async function RegistriesPage() {
  const [t, tSettings, { canAdminister }] = await Promise.all([
    getTranslations("Registries"),
    getTranslations("SettingsPage"),
    getViewerCapabilities(),
  ]);
  // Started here, awaited by the form only when it opens.
  const secrets = canAdminister ? secretOptions() : Promise.resolve([]);

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: tSettings("title"), href: "/settings" },
          { label: t("title") },
        ],
        description: t("description"),
        controls: canAdminister ? (
          <AddRegistryButton secrets={secrets} />
        ) : undefined,
      }}
    >
      <Suspense
        fallback={
          <TableSkeleton
            rows={4}
            columns={[
              { header: t("table.name"), barClassName: "h-4 w-32" },
              { header: t("table.source"), barClassName: "h-4 w-40" },
              {
                header: t("table.type"),
                headerClassName: "w-[90px]",
                barClassName: "h-4 w-12",
              },
              {
                header: t("table.trust"),
                headerClassName: "w-[120px]",
                barClassName: "h-5 w-16 rounded-full",
              },
              {
                header: t("table.items"),
                headerClassName: "w-[70px]",
                barClassName: "h-4 w-8",
              },
              {
                header: t("table.sync"),
                headerClassName: "w-[200px]",
                barClassName: "h-4 w-24",
              },
            ]}
          />
        }
      >
        <RegistriesContent secrets={secrets} />
      </Suspense>
    </ContentBlock>
  );
}
