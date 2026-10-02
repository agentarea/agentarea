import { getTranslations } from "next-intl/server";
import RetryEmptyState from "@/components/EmptyState/RetryEmptyState";
import { listSecrets } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";
import { SecretsEmptyState } from "./SecretsEmptyState";
import { SecretsTable, type Secret } from "./SecretsTable";

export async function SecretsData() {
  const t = await getTranslations("SecretsPage");
  let secrets: Secret[] = [];
  let error: string | null = null;

  try {
    const result = await listSecrets();
    if (result.error) {
      console.error("Failed to fetch secrets:", result.error);
      error = apiErrorMessage(result, t("loadFailed"));
    } else {
      secrets = (result.data as Secret[] | undefined) ?? [];
    }
  } catch (e) {
    console.error("Failed to load secrets:", e);
    error = e instanceof Error ? e.message : t("loadFailed");
  }

  if (error) {
    return (
      <RetryEmptyState
        title={t("loadFailedTitle")}
        description={error}
        iconsType="mcp"
      />
    );
  }

  return secrets.length === 0 ? (
    <SecretsEmptyState />
  ) : (
    <SecretsTable secrets={secrets} />
  );
}
