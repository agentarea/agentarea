import EmptyState from "@/components/EmptyState";
import { getInbox, type TaskWithAgent } from "@/lib/api";
import TasksList from "@/app/(main)/tasks/components/TasksList";

export async function InboxData() {
  let items: TaskWithAgent[] = [];
  let error: string | null = null;

  try {
    const { data, error: fetchError } = await getInbox();
    if (fetchError) {
      error = "Failed to load inbox";
    } else {
      items = (data as any)?.items || [];
    }
  } catch {
    error = "Failed to load inbox";
  }

  if (error) {
    return <div className="py-6 text-center text-red-500">{error}</div>;
  }

  if (items.length === 0) {
    return (
      <EmptyState
        title="No items requiring attention"
        description="Tasks waiting for approval, completed tasks, and failed tasks will appear here."
        iconsType="tasks"
      />
    );
  }

  return <TasksList initialTasks={items} viewMode="list" />;
}
