"use client";

import { useTranslations } from "next-intl";
import Table from "@/components/Table/Table";
import type { RegistryRow } from "./registry-rows";
import { RegistrySection, useRegistryColumns } from "./RegistryTableParts";

/** The platform's registries every workspace sees; the operator manages them, so no actions. */
export default function PlatformRegistriesTable({
  registries,
}: {
  registries: RegistryRow[];
}) {
  const t = useTranslations("Registries");
  const { name, type, trust, items, sync } = useRegistryColumns<RegistryRow>();

  return (
    <RegistrySection
      title={t("platformSection.title")}
      description={t("platformSection.description")}
    >
      {registries.length === 0 ? (
        <div className="py-6 text-center text-sm text-muted-foreground">
          {t("platformSection.empty")}
        </div>
      ) : (
        <Table data={registries} columns={[name, type, trust, items, sync]} />
      )}
    </RegistrySection>
  );
}
