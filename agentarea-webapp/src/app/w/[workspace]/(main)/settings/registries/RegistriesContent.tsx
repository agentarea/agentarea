import { getTranslations } from "next-intl/server";
import RetryEmptyState from "@/components/EmptyState/RetryEmptyState";
import type { SelectableSecret } from "@/components/SecretSelect";
import { listWorkspaceRegistries } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";
import RegistriesClient from "./RegistriesClient";

export default async function RegistriesContent({
  secrets,
}: {
  secrets: Promise<SelectableSecret[]>;
}) {
  const [result, t] = await Promise.all([
    listWorkspaceRegistries(),
    getTranslations("Registries"),
  ]);

  if (result.error || !result.data) {
    console.error("Failed to load registries", result.status, result.error);
    return (
      <RetryEmptyState
        title={t("loadFailed")}
        description={apiErrorMessage(result, t("loadFailed"))}
      />
    );
  }

  return <RegistriesClient registries={result.data} secrets={secrets} />;
}
