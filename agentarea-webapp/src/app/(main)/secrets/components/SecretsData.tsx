import EmptyState from "@/components/EmptyState";
import { listSecrets } from "@/lib/api";
import { CreateSecretDialog } from "./CreateSecretDialog";
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
      <EmptyState
        title="Couldn't load secrets"
        description={error}
        iconsType="mcp"
      />
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-sm font-medium">Workspace secrets</h2>
          <p className="text-sm text-muted-foreground">
            Every credential this workspace holds. Values are encrypted and
            never shown again once saved. The ones marked managed belong to a
            connection and are changed there; your own can be reused across
            several connections, and rotating one updates all of them at once.
          </p>
        </div>
        <CreateSecretDialog />
      </div>

      {secrets.length === 0 ? (
        <EmptyState
          title="No secrets yet"
          description="Nothing here holds a credential. Create a secret to reuse it across LLM providers and API connections, instead of pasting the same key into each one."
          iconsType="mcp"
        />
      ) : (
        <SecretsTable secrets={secrets} />
      )}
    </div>
  );
}
