import { getTranslations } from "next-intl/server";
import { BoardGrid } from "@/components/board";
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
    const t = await getTranslations("DashboardPage");
    return (
      <div className="p-6">
        <EmptyState
          title={t("couldntLoadTitle")}
          description={error}
          iconsType="tasks"
        />
      </div>
    );
  }

  if (!data) return null;

  return (
    <BoardGrid
      topLeft={<SpendCard spend={data.spend} trend={data.daily_spend} />}
      topRight={<ActivityStrip data={data.daily_tasks} />}
      bottomLeft={<AgentRows agents={data.agents} />}
      bottomRight={<BlockersPanel blockers={data.blockers} />}
    />
  );
}
