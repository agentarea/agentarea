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
  running: <Loader2 className="h-5 w-5 text-blue-500 animate-spin" />,
  completed: <CheckCircle2 className="h-5 w-5 text-green-500" />,
  success: <CheckCircle2 className="h-5 w-5 text-green-500" />,
  failed: <XCircle className="h-5 w-5 text-red-500" />,
  error: <XCircle className="h-5 w-5 text-red-500" />,
  warning: <AlertTriangle className="h-5 w-5 text-yellow-500" />,
  paused: <AlertTriangle className="h-5 w-5 text-yellow-500" />
};

function AllTasksTable({ tasks }: { tasks: TaskWithAgent[] }) {
  return (
    <div className="grid gap-4">
      {tasks.map((task) => (
        <TaskNavigationWrapper key={task.id} taskId={task.id.toString()}>
          <div className="group hover:shadow-md transition-all duration-200 border rounded-xl p-6 bg-white dark:bg-gray-900 cursor-pointer">
            <div className="flex items-start justify-between">
              <div className="flex-1 min-w-0">
                <div className="flex items-start gap-4">
                  {/* Status Indicator */}
                  <div className="flex-shrink-0 mt-1">
                    <div className={`w-3 h-3 rounded-full ${
                      task.status === "running" ? "bg-blue-500 animate-pulse" :
                      task.status === "completed" || task.status === "success" ? "bg-green-500" :
                      task.status === "paused" ? "bg-yellow-500" :
                      task.status === "failed" || task.status === "error" ? "bg-red-500" :
                      "bg-gray-400"
                    }`} />
                  </div>

                  {/* Main Content */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-start justify-between mb-3">
                      <div className="flex-1 min-w-0">
                        <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100 line-clamp-2 group-hover:text-primary transition-colors">
                          {task.description}
                        </h3>
                        <div className="flex items-center gap-4 mt-2 text-sm text-gray-600 dark:text-gray-400">
                          <div className="flex items-center gap-1">
                            <Bot className="h-4 w-4" />
                            <span>{task.agent_name || "Unknown Agent"}</span>
                          </div>
                          <div className="flex items-center gap-1">
                            <Calendar className="h-4 w-4" />
                            <span>{new Date(task.created_at).toLocaleDateString()}</span>
                          </div>
                          <span className="text-xs text-gray-500">
                            ID: {task.id.toString().slice(-8)}
                          </span>
                        </div>
                      </div>

                      {/* Status Badge */}
                      <div className="flex items-center gap-2 ml-4">
                        {statusIcons[task.status as keyof typeof statusIcons]}
                        <Badge variant={
                          task.status === "running" ? "default" :
                          task.status === "paused" ? "secondary" :
                          task.status === "completed" || task.status === "success" ? "default" :
                          "destructive"
                        } className="whitespace-nowrap">
                          {task.status.charAt(0).toUpperCase() + task.status.slice(1)}
                        </Badge>
                      </div>
                    </div>

                    {/* Agent Description */}
                    {task.agent_description && (
                      <p className="text-sm text-gray-600 dark:text-gray-400 line-clamp-2 mb-3">
                        {task.agent_description}
                      </p>
                    )}

                    {/* Result Preview for completed tasks */}
                    {task.result && (task.status === "completed" || task.status === "success" || task.status === "failed") && (
                      <div className="mb-3">
                        <div className="bg-gray-50 dark:bg-gray-800 rounded-lg p-3">
                          <p className="text-xs text-gray-500 mb-1">Result Preview</p>
                          <p className="text-sm font-mono text-gray-700 dark:text-gray-300 truncate">
                            {JSON.stringify(task.result).slice(0, 100)}
                            {JSON.stringify(task.result).length > 100 && "..."}
                          </p>
                        </div>
                      </div>
                    )}

                    {/* Footer with execution info */}
                    <div className="flex items-center justify-between pt-3 border-t border-gray-100 dark:border-gray-800">
                      <div className="flex items-center gap-4 text-xs text-gray-500">
                        {task.execution_id && (
                          <span className="font-mono bg-gray-100 dark:bg-gray-800 px-2 py-1 rounded">
                            {task.execution_id.slice(-8)}
                          </span>
                        )}
                        <span>
                          {task.status === "completed" || task.status === "success" || task.status === "failed" 
                            ? `Completed ${new Date(task.created_at).toLocaleTimeString()}`
                            : new Date(task.created_at).toLocaleTimeString()
                          }
                        </span>
                      </div>
                      
                      {/* Status-specific indicators */}
                      {task.status === "running" && (
                        <div className="flex items-center gap-2 text-xs text-blue-600">
                          <div className="w-2 h-2 bg-blue-500 rounded-full animate-pulse" />
                          <span>In Progress</span>
                        </div>
                      )}
                      {(task.status === "success" || task.status === "completed") && (
                        <div className="flex items-center gap-2 text-xs text-green-600">
                          <CheckCircle2 className="w-3 h-3" />
                          <span>Completed</span>
                        </div>
                      )}
                      {(task.status === "failed" || task.status === "error") && (
                        <div className="flex items-center gap-2 text-xs text-red-600">
                          <XCircle className="w-3 h-3" />
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
  const searchQuery = typeof searchParams.search === 'string' ? searchParams.search : "";
  const statusFilter = typeof searchParams.status === 'string' ? searchParams.status : "all";

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
        controls: (
          <div className="flex gap-4">
            <Button variant="outline" disabled className="gap-2">
              <Calendar className="h-4 w-4" />
              Date Range
            </Button>
            <Button variant="outline" disabled className="gap-2">
              <Download className="h-4 w-4" />
              Export
            </Button>
          </div>
        )
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

        {/* Display Error */}
        {error && (
          <div className="text-center py-10">
            <XCircle className="h-8 w-8 mx-auto mb-4 text-destructive" />
            <p className="text-destructive mb-4">{error}</p>
          </div>
        )}

        {/* All Tasks Display */}
        {filteredTasks.length === 0 ? (
          <div className="text-center py-16 px-6">
            <div className="max-w-sm mx-auto">
              {hasActiveFilters ? (
                <>
                  <div className="w-20 h-20 mx-auto mb-6 bg-gray-100 dark:bg-gray-800 rounded-full flex items-center justify-center">
                    <XCircle className="h-10 w-10 text-gray-400" />
                  </div>
                  <h3 className="text-xl font-semibold mb-3 text-gray-900 dark:text-gray-100">No matching tasks</h3>
                  <p className="text-gray-600 dark:text-gray-400 mb-6 leading-relaxed">
                    No tasks match your current filters. Try adjusting your search or status filter to find what you're looking for.
                  </p>
                  <TasksNavigationButtons type="clear-filters" variant="outline" />
                </>
              ) : (
                <>
                  <div className="w-20 h-20 mx-auto mb-6 bg-blue-50 dark:bg-blue-900/20 rounded-full flex items-center justify-center">
                    <Bot className="h-10 w-10 text-blue-500" />
                  </div>
                  <h3 className="text-xl font-semibold mb-3 text-gray-900 dark:text-gray-100">No tasks yet</h3>
                  <p className="text-gray-600 dark:text-gray-400 mb-6 leading-relaxed">
                    No tasks have been created yet. Deploy an agent and create a new task to get started.
                  </p>
                  <div className="flex gap-3 justify-center">
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