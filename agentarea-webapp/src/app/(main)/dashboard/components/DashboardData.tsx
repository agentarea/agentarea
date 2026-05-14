import EmptyState from "@/components/EmptyState";
import { getDashboard } from "@/lib/api-dashboard";
import { ActivityStrip } from "./ActivityStrip";
import { AgentRows } from "./AgentRows";
import { BlockersPanel } from "./BlockersPanel";
import { SpendCard } from "./SpendCard";

export async function DashboardData() {
  let data: Awaited<ReturnType<typeof getDashboard>> | null = null;
  let error: string | null = null;

  try {
    data = await getDashboard();
  } catch (e) {
    error = e instanceof Error ? e.message : "Failed to load dashboard";
  }

  if (error) {
    return (
      <EmptyState
        title="Couldn't load dashboard"
        description={error}
        iconsType="tasks"
      />
    );
  }

  if (!data) return null;

  return (
    <div>
      <div className="grid gap-x-10 gap-y-6 lg:grid-cols-5 lg:divide-x lg:divide-border/50">
        <div className="lg:col-span-3 lg:pr-10">
          <SpendCard spend={data.spend} trend={data.daily_spend} />
        </div>
        <div className="lg:col-span-2 lg:pl-10">
          <ActivityStrip data={data.daily_tasks} />
        </div>
      </div>

      <div className="my-6 border-t border-border/50" />

      <div className="grid gap-x-10 gap-y-6 lg:grid-cols-3 lg:divide-x lg:divide-border/50">
        <div className="lg:col-span-2 lg:pr-10">
          <AgentRows agents={data.agents} />
        </div>
        <div className="lg:col-span-1 lg:pl-10">
          <BlockersPanel blockers={data.blockers} />
        </div>
      </div>
    </div>
  );
}
