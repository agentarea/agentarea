import { getTranslations } from "next-intl/server";
import type { ApiKeyResponse } from "@/api/client/types.gen";
import RetryEmptyState from "@/components/EmptyState/RetryEmptyState";
import { listAPIKeys } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";
import { getViewerCapabilities } from "@/lib/workspace-context";
import APIKeysClient from "./APIKeysClient";

const APIKeyStatus = {
  ACTIVE: "active",
  REVOKED: "revoked",
  EXPIRED: "expired",
} as const;

function deriveStatus(key: ApiKeyResponse): (typeof APIKeyStatus)[keyof typeof APIKeyStatus] {
  if (!key.is_active) return APIKeyStatus.REVOKED;
  if (key.expires_at && new Date(key.expires_at) < new Date()) return APIKeyStatus.EXPIRED;
  return APIKeyStatus.ACTIVE;
}

export default async function APIKeysContent() {
  const [result, { canAdminister }, t, tAdmin] = await Promise.all([
    listAPIKeys(),
    getViewerCapabilities(),
    getTranslations("APIKeysPage"),
    getTranslations("AdminOnly"),
  ]);

  if (result.error || !result.data) {
    console.error("Failed to load API keys", result.status, result.error);
    return (
      <RetryEmptyState
        title={t("error.loadFailed")}
        description={apiErrorMessage(result, t("error.loadFailed"))}
        iconsType="apiKey"
      />
    );
  }

  const keys = result.data.map((key) => ({
    ...key,
    status: deriveStatus(key),
  }));

  return (
    <>
      {!canAdminister && (
        <p className="mb-3 text-xs text-muted-foreground">
          {tAdmin("areas.apiKeys.description")}
        </p>
      )}
      <APIKeysClient initialKeys={keys} />
    </>
  );
}
