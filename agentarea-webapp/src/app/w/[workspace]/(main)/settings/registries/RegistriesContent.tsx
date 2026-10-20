import { getTranslations } from "next-intl/server";
import RetryEmptyState from "@/components/EmptyState/RetryEmptyState";
import type { SelectableSecret } from "@/components/SecretSelect";
import SectionLoadError from "@/components/SectionLoadError";
import { listPlatformRegistries, listWorkspaceRegistries } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";
import PlatformRegistriesTable from "./PlatformRegistriesTable";
import RegistriesClient from "./RegistriesClient";
import { toPlatformRegistryRow } from "./registry-rows";

export default async function RegistriesContent({
  secrets,
}: {
  secrets: Promise<SelectableSecret[]>;
}) {
  const [workspace, platform, t] = await Promise.all([
    listWorkspaceRegistries(),
    listPlatformRegistries(),
    getTranslations("Registries"),
  ]);

  if (workspace.error || !workspace.data) {
    console.error(
      "Failed to load registries",
      workspace.status,
      workspace.error
    );
    return (
      <RetryEmptyState
        title={t("loadFailed")}
        description={apiErrorMessage(workspace, t("loadFailed"))}
      />
    );
  }
  if (platform.error || !platform.data) {
    console.error(
      "Failed to load platform registries",
      platform.status,
      platform.error
    );
  }

  return (
    <div className="space-y-8">
      <RegistriesClient registries={workspace.data} secrets={secrets} />
      {platform.data ? (
        <PlatformRegistriesTable
          registries={platform.data.map(toPlatformRegistryRow)}
        />
      ) : (
        <SectionLoadError
          message={apiErrorMessage(platform, t("platformSection.loadFailed"))}
        />
      )}
    </div>
  );
}
