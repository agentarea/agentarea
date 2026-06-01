import Link from "next/link";
import EmptyState from "@/components/EmptyState";
import { getDashboard } from "@/lib/api-dashboard";
import { SpendCard } from "@/app/(main)/dashboard/components/SpendCard";

export async function BudgetsData() {
  let data: Awaited<ReturnType<typeof getDashboard>> | null = null;
  let error: string | null = null;

  try {
    data = await getDashboard();
  } catch (e) {
    console.error("Failed to load budgets data:", e);
    error = e instanceof Error ? e.message : "Failed to load budget data";
  }

  if (error) {
    return (
      <EmptyState
        title="Couldn't load budget data"
        description={error}
        iconsType="payments"
      />
    );
  }

  if (!data) return null;

  return (
    <div className="space-y-8">
      <div className="max-w-lg">
        <SpendCard spend={data.spend} trend={data.daily_spend} />
      </div>

      <div>
        <h3 className="mb-3 text-[13px] font-medium text-foreground">
          Workspace cap settings
        </h3>
        <div className="rounded border border-border/60 bg-muted/30 px-4 py-3 text-sm text-muted-foreground">
          <p>Configure spending limits in workspace settings.</p>
          <Link
            href="/admin/workspace"
            className="mt-2 inline-block text-[13px] font-medium text-foreground underline-offset-4 hover:underline"
          >
            Open workspace settings
          </Link>
        </div>
      </div>
    </div>
  );
}
