import RetryEmptyState from "@/components/EmptyState/RetryEmptyState";
import { listSecrets } from "@/lib/api";
import { SecretsEmptyState } from "./SecretsEmptyState";
import { SecretsTable, type Secret } from "./SecretsTable";

export async function SecretsData() {
  let secrets: Secret[] = [];
  let error: string | null = null;

  try {
    const { data, error: apiError } = await listSecrets();
    if (apiError) {
      console.error("Failed to fetch secrets:", apiError);
      error = "Failed to load secrets";
    } else {
      secrets = (data as Secret[] | undefined) ?? [];
    }
  } catch (e) {
    console.error("Failed to load secrets:", e);
    error = e instanceof Error ? e.message : "Failed to load secrets";
  }

  if (error) {
    return (
      <RetryEmptyState
        title="Couldn't load secrets"
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
