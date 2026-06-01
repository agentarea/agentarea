import EmptyState from "@/components/EmptyState";
import { listGovernancePolicies } from "@/lib/api";
import { PoliciesTable } from "./PoliciesTable";

type Policy = {
  id: string;
  scope_type: string;
  scope_id: string;
  enabled: boolean;
  document: Record<string, unknown>;
};

export async function PoliciesData() {
  let policies: Policy[] = [];
  let error: string | null = null;

  try {
    const { data, error: apiError } = await listGovernancePolicies();
    if (apiError) {
      console.error("Failed to fetch governance policies:", apiError);
      error = "Failed to load policies";
    } else {
      policies = ((data as any) ?? []) as Policy[];
    }
  } catch (e) {
    console.error("Failed to load policies data:", e);
    error = e instanceof Error ? e.message : "Failed to load policies";
  }

  return (
    <div className="space-y-4">
      <div className="border-l-2 border-border/60 py-2 pl-3 text-sm text-muted-foreground">
        Read-only view. Editable policies UI coming soon.
      </div>

      {error ? (
        <EmptyState
          title="Couldn't load policies"
          description={error}
          iconsType="audit"
        />
      ) : policies.length === 0 ? (
        <EmptyState
          title="No policies configured"
          description="Governance policies define rules applied to agents and workspaces."
          iconsType="audit"
        />
      ) : (
        <PoliciesTable policies={policies} />
      )}
    </div>
  );
}
