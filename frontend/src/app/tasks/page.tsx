import React from "react";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import {
  Bot,
  Calendar,
  Download,
  XCircle,
  CheckCircle2,
  AlertTriangle,
  Loader2,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getAllTasks, type TaskResponse } from "@/lib/api";
import { TasksFilters } from "./TasksFilters";
import { TasksActions } from "./TasksActions";
import { TaskNavigationWrapper } from "./TaskNavigationWrapper";
import { TasksNavigationButtons } from "./TasksNavigationButtons";

// Enhanced task type with agent information
interface TaskWithAgent extends TaskResponse {
  agent_name?: string;
  agent_description?: string | null;
}

interface TasksPageProps {
  searchParams: { [key: string]: string | string[] | undefined };
}

const statusIcons = {
  running: <Loader2 className="h-3 w-3 text-blue-500 animate-spin" />,
  completed: <CheckCircle2 className="h-3 w-3 text-green-500" />,
  success: <CheckCircle2 className="h-3 w-3 text-green-500" />,
  failed: <XCircle className="h-3 w-3 text-red-500" />,
  error: <XCircle className="h-3 w-3 text-red-500" />,
  warning: <AlertTriangle className="h-3 w-3 text-yellow-500" />,
  paused: <AlertTriangle className="h-3 w-3 text-yellow-500" />
};

function AllTasksTable({ tasks }: { tasks: TaskWithAgent[] }) {
  return (
    <div className="grid gap-2">
      {tasks.map((task) => (
        <TaskNavigationWrapper key={task.id} taskId={task.id.toString()}>
          <div className="group hover:shadow-md transition-all duration-200 border rounded-lg p-3 bg-white dark:bg-gray-900 cursor-pointer">
            <div className="flex items-start justify-between">
              <div className="flex-1 min-w-0">
                <div className="flex items-start gap-3">
                  {/* Smaller Status Indicator */}
                  <div className="flex-shrink-0 mt-0.5">
                    <div className={`w-2 h-2 rounded-full ${
                      task.status === "running" ? "bg-blue-500 animate-pulse" :
                      task.status === "completed" || task.status === "success" ? "bg-green-500" :
                      task.status === "paused" ? "bg-yellow-500" :
                      task.status === "failed" || task.status === "error" ? "bg-red-500" :
                      "bg-gray-400"
                    }`} />
                  </div>

                  {/* Compact Main Content */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-start justify-between mb-2">
                      <div className="flex-1 min-w-0">
                        <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100 line-clamp-2 group-hover:text-primary transition-colors">
                          {task.description}
                        </h3>
                        <div className="flex items-center gap-3 mt-1 text-xs text-gray-600 dark:text-gray-400">
                          <div className="flex items-center gap-1">
                            <Bot className="h-3 w-3" />
                            <span>{task.agent_name || "Unknown Agent"}</span>
                          </div>
                          <div className="flex items-center gap-1">
                            <Calendar className="h-3 w-3" />
                            <span>{new Date(task.created_at).toLocaleDateString()}</span>
                          </div>
                          <span className="text-xs text-gray-500">
                            ID: {task.id.toString().slice(-8)}
                          </span>
                        </div>
                      </div>

                      {/* Compact Status Badge */}
                      <div className="flex items-center gap-1 ml-3">
                        {statusIcons[task.status as keyof typeof statusIcons]}
                        <Badge variant={
                          task.status === "running" ? "default" :
                          task.status === "paused" ? "secondary" :
                          task.status === "completed" || task.status === "success" ? "default" :
                          "destructive"
                        } className="whitespace-nowrap text-xs px-1.5 py-0.5">
                          {task.status.charAt(0).toUpperCase() + task.status.slice(1)}
                        </Badge>
                      </div>
                    </div>

                    {/* Compact Agent Description */}
                    {task.agent_description && (
                      <p className="text-xs text-gray-600 dark:text-gray-400 line-clamp-1 mb-2">
                        {task.agent_description}
                      </p>
                    )}

                    {/* Compact Result Preview */}
                    {task.result && (task.status === "completed" || task.status === "success" || task.status === "failed") && (
                      <div className="mb-2">
                        <div className="bg-gray-50 dark:bg-gray-800 rounded p-2">
                          <p className="text-xs text-gray-500 mb-0.5">Result</p>
                          <p className="text-xs font-mono text-gray-700 dark:text-gray-300 truncate">
                            {JSON.stringify(task.result).slice(0, 80)}
                            {JSON.stringify(task.result).length > 80 && "..."}
                          </p>
                        </div>
                      </div>
                    )}

                    {/* Compact Footer */}
                    <div className="flex items-center justify-between pt-2 border-t border-gray-100 dark:border-gray-800">
                      <div className="flex items-center gap-2 text-xs text-gray-500">
                        {task.execution_id && (
                          <span className="font-mono bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 rounded text-xs">
                            {task.execution_id.slice(-6)}
                          </span>
                        )}
                        <span>
                          {task.status === "completed" || task.status === "success" || task.status === "failed" 
                            ? `${new Date(task.created_at).toLocaleTimeString()}`
                            : new Date(task.created_at).toLocaleTimeString()
                          }
                        </span>
                      </div>
                      
                      {/* Compact Status indicators */}
                      {task.status === "running" && (
                        <div className="flex items-center gap-1 text-xs text-blue-600">
                          <div className="w-1.5 h-1.5 bg-blue-500 rounded-full animate-pulse" />
                          <span>Running</span>
                        </div>
                      )}
                      {(task.status === "success" || task.status === "completed") && (
                        <div className="flex items-center gap-1 text-xs text-green-600">
                          <CheckCircle2 className="w-2.5 h-2.5" />
                          <span>Done</span>
                        </div>
                      )}
                      {(task.status === "failed" || task.status === "error") && (
                        <div className="flex items-center gap-1 text-xs text-red-600">
                          <XCircle className="w-2.5 h-2.5" />
                          <span>Failed</span>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </TaskNavigationWrapper>
      ))}
    </div>
  );
}

export default async function TasksPage({ searchParams }: TasksPageProps) {
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

  // Server-side filtering based on search params
  const resolvedSearchParams = await searchParams;
  const searchQuery = typeof resolvedSearchParams.search === 'string' ? resolvedSearchParams.search : "";
  const statusFilter = typeof resolvedSearchParams.status === 'string' ? resolvedSearchParams.status : "all";

  // Apply filters on server
  let filteredTasks = allTasks;

  if (searchQuery.trim()) {
    const query = searchQuery.toLowerCase();
    filteredTasks = filteredTasks.filter(task => 
      task.description.toLowerCase().includes(query) ||
      (task.agent_name && task.agent_name.toLowerCase().includes(query))
    );
  }

  if (statusFilter !== "all") {
    filteredTasks = filteredTasks.filter(task => task.status === statusFilter);
  }

  const hasActiveFilters = searchQuery.trim() !== "" || statusFilter !== "all";

  return (
    <ContentBlock
      header={{
        // title: "Agent Workflows",
        breadcrumb: [
          {label: "Agent Workflow"},
        ],
        description: "Monitor, manage, and review your agent workflows",
      }}
    >
      <div>
        {/* Actions Bar */}
        <TasksActions />

        {/* Filter Controls */}
        <TasksFilters 
          searchQuery={searchQuery}
          statusFilter={statusFilter}
          hasActiveFilters={hasActiveFilters}
        />

        {/* Compact Error Display */}
        {error && (
          <div className="text-center py-6">
            <XCircle className="h-6 w-6 mx-auto mb-2 text-destructive" />
            <p className="text-destructive text-sm">{error}</p>
          </div>
        )}

        {/* Compact Tasks Display */}
        {filteredTasks.length === 0 ? (
          <div className="text-center py-8 px-4">
            <div className="max-w-sm mx-auto">
              {hasActiveFilters ? (
                <>
                  <div className="w-12 h-12 mx-auto mb-3 bg-gray-100 dark:bg-gray-800 rounded-full flex items-center justify-center">
                    <XCircle className="h-6 w-6 text-gray-400" />
                  </div>
                  <h3 className="text-base font-semibold mb-2 text-gray-900 dark:text-gray-100">No matching tasks</h3>
                  <p className="text-gray-600 dark:text-gray-400 mb-4 text-sm">
                    No tasks match your filters. Try adjusting your search or status filter.
                  </p>
                  <TasksNavigationButtons type="clear-filters" variant="outline" />
                </>
              ) : (
                <>
                  <div className="w-12 h-12 mx-auto mb-3 bg-blue-50 dark:bg-blue-900/20 rounded-full flex items-center justify-center">
                    <Bot className="h-6 w-6 text-blue-500" />
                  </div>
                  <h3 className="text-base font-semibold mb-2 text-gray-900 dark:text-gray-100">No tasks yet</h3>
                  <p className="text-gray-600 dark:text-gray-400 mb-4 text-sm">
                    Deploy an agent and create a new task to get started.
                  </p>
                  <div className="flex gap-2 justify-center">
                    <TasksNavigationButtons type="deploy-agent" />
                    <TasksNavigationButtons type="browse-agents" variant="outline" />
                  </div>
                </>
              )}
            </div>
          </div>
        ) : (
          <AllTasksTable tasks={filteredTasks} />
        )}
      </div>
    </ContentBlock>
  );
}
