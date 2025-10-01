import { getAllTasks, type TaskWithAgent } from "@/lib/api";
import EmptyState from "@/components/EmptyState";
import TaskItem from "./TaskItem";

interface TasksDataProps {
  searchQuery?: string;
}

export async function TasksData({ searchQuery = "" }: TasksDataProps) {
  // Fetch tasks on the server
  let allTasks: TaskWithAgent[] = [];
  let error: string | null = null;

  try {
    const { data: tasksData, error: tasksError } = await getAllTasks();
    if (tasksError) {
      error = "Failed to load tasks";
    } else {
      allTasks = tasksData || [];
    }
  } catch {
    error = "Failed to load tasks";
  }

  // Filter tasks based on search query
  let filteredTasks = allTasks;
  if (searchQuery.trim()) {
    const query = searchQuery.toLowerCase();
    filteredTasks = allTasks.filter(task => 
      task.description?.toLowerCase().includes(query) ||
      task.agent_name?.toLowerCase().includes(query) ||
      task.status?.toLowerCase().includes(query)
    );
  }

  const hasNoTasks = allTasks.length === 0;
  const hasNoResults = filteredTasks.length === 0 && !hasNoTasks;

  if (hasNoTasks) {
    return (
      <EmptyState 
        title="No tasks found"
        iconsType="tasks"
      />
    );
  }

  if (hasNoResults) {
    return (
      <EmptyState 
        title="No matching tasks"
        description={`No tasks match your search query: "${searchQuery}"`}
        iconsType="tasks"
      />
    );
  }

  return (
    // <div className="flex flex-col gap-2">
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
        {error ? (
            <div className="text-center py-6 text-red-500">
                {error}
            </div>
        ) : (
            filteredTasks.map((task) => (
                <TaskItem key={task.id} task={task} />
            ))
        )}
    </div>
  );
}

