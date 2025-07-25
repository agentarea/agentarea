import React from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getAllTasks, type TaskResponse } from "@/lib/api";
import { TasksFilters } from "./TasksFilters";
import { TasksActions } from "./TasksActions";
import { TaskNavigationWrapper } from "./TaskNavigationWrapper";

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

function TaskTable({ tasks }: { tasks: TaskWithAgent[] }) {
  return (
    <div className="rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Task</TableHead>
            <TableHead>Agent</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Created</TableHead>
            <TableHead>Execution ID</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {tasks.map((task) => (
            <TaskNavigationWrapper key={task.id} taskId={task.id.toString()}>
              <TableRow>
                <TableCell className="font-medium">
                  <div className="flex items-center gap-2">
                    <Bot className="h-4 w-4 text-primary" />
                    <div>
                      <p className="font-medium">{task.description}</p>
                      <p className="text-sm text-muted-foreground">ID: {task.id.toString().slice(-8)}</p>
                    </div>
                  </div>
                </TableCell>
                <TableCell>
                  <div>
                    <p className="font-medium">{task.agent_name || "Unknown Agent"}</p>
                    <p className="text-sm text-muted-foreground">
                      {task.agent_description || "No description"}
                    </p>
                  </div>
                </TableCell>
                <TableCell>
                  <div className="flex items-center gap-2">
                    {statusIcons[task.status as keyof typeof statusIcons]}
                    <Badge variant={
                      task.status === "running" ? "default" :
                      task.status === "paused" ? "secondary" :
                      task.status === "completed" || task.status === "success" ? "default" :
                      "destructive"
                    }>
                      {task.status}
                    </Badge>
                  </div>
                </TableCell>
                <TableCell>
                  {new Date(task.created_at).toLocaleString()}
                </TableCell>
                <TableCell>
                  <code className="text-xs bg-muted px-2 py-1 rounded">
                    {task.execution_id || "N/A"}
                  </code>
                </TableCell>
              </TableRow>
            </TaskNavigationWrapper>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function CompletedTaskTable({ tasks }: { tasks: TaskWithAgent[] }) {
  return (
    <div className="rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Task</TableHead>
            <TableHead>Agent</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Created</TableHead>
            <TableHead>Result</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {tasks.map((task) => (
            <TaskNavigationWrapper key={task.id} taskId={task.id.toString()}>
              <TableRow>
                <TableCell className="font-medium">
                  <div className="flex items-center gap-2">
                    <Bot className="h-4 w-4 text-primary" />
                    <div>
                      <p className="font-medium">{task.description}</p>
                      <p className="text-sm text-muted-foreground">ID: {task.id.toString().slice(-8)}</p>
                    </div>
                  </div>
                </TableCell>
                <TableCell>
                  <div>
                    <p className="font-medium">{task.agent_name || "Unknown Agent"}</p>
                    <p className="text-sm text-muted-foreground">
                      {task.agent_description || "No description"}
                    </p>
                  </div>
                </TableCell>
                <TableCell>
                  <div className="flex items-center gap-2">
                    {statusIcons[task.status as keyof typeof statusIcons]}
                    <Badge variant={
                      task.status === "success" || task.status === "completed" ? "default" :
                      task.status === "failed" || task.status === "error" ? "destructive" :
                      "secondary"
                    }>
                      {task.status}
                    </Badge>
                  </div>
                </TableCell>
                <TableCell>
                  {new Date(task.created_at).toLocaleString()}
                </TableCell>
                <TableCell>
                  <div className="max-w-xs truncate">
                    {task.result ? 
                      JSON.stringify(task.result).slice(0, 100) + "..." : 
                      "No result available"
                    }
                  </div>
                </TableCell>
              </TableRow>
            </TaskNavigationWrapper>
          ))}
        </TableBody>
      </Table>
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

  // Separate tasks by status
  const activeTasks = filteredTasks.filter(task => 
    task.status === "running" || task.status === "paused" || task.status === "error"
  );
  
  const completedTasks = filteredTasks.filter(task => 
    task.status === "completed" || task.status === "success" || task.status === "failed"
  );

  const hasActiveFilters = searchQuery.trim() !== "" || statusFilter !== "all";
  const defaultTab = typeof searchParams.tab === 'string' ? searchParams.tab : "active";

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

        {/* Task Tabs */}
        <Tabs defaultValue={defaultTab} className="w-full">
          <TabsList className="mb-6">
            <TabsTrigger value="active">
              Active Tasks
              {activeTasks.length > 0 && (
                <Badge variant="secondary" className="ml-2">
                  {activeTasks.length}
                </Badge>
              )}
            </TabsTrigger>
            <TabsTrigger value="completed">
              Completed Tasks
              {completedTasks.length > 0 && (
                <Badge variant="secondary" className="ml-2">
                  {completedTasks.length}
                </Badge>
              )}
            </TabsTrigger>
          </TabsList>

          <TabsContent value="active">
            {activeTasks.length === 0 ? (
              <div className="text-center py-10">
                {hasActiveFilters ? (
                  <>
                    <XCircle className="h-12 w-12 mx-auto mb-4 text-muted-foreground" />
                    <h3 className="text-lg font-semibold mb-2">No matching active tasks</h3>
                    <p className="text-muted-foreground mb-4">
                      No active tasks match your current filters. Try adjusting your search or status filter.
                    </p>
                  </>
                ) : (
                  <>
                    <Bot className="h-12 w-12 mx-auto mb-4 text-muted-foreground" />
                    <h3 className="text-lg font-semibold mb-2">No active tasks</h3>
                    <p className="text-muted-foreground mb-4">
                      There are currently no active tasks running. Create a new task to get started.
                    </p>
                  </>
                )}
              </div>
            ) : (
              <TaskTable tasks={activeTasks} />
            )}
          </TabsContent>

          <TabsContent value="completed">
            {completedTasks.length === 0 ? (
              <div className="text-center py-10">
                {hasActiveFilters ? (
                  <>
                    <XCircle className="h-12 w-12 mx-auto mb-4 text-muted-foreground" />
                    <h3 className="text-lg font-semibold mb-2">No matching completed tasks</h3>
                    <p className="text-muted-foreground mb-4">
                      No completed tasks match your current filters. Try adjusting your search or status filter.
                    </p>
                  </>
                ) : (
                  <>
                    <CheckCircle2 className="h-12 w-12 mx-auto mb-4 text-muted-foreground" />
                    <h3 className="text-lg font-semibold mb-2">No completed tasks</h3>
                    <p className="text-muted-foreground">
                      Completed tasks will appear here once they finish execution.
                    </p>
                  </>
                )}
              </div>
            ) : (
              <CompletedTaskTable tasks={completedTasks} />
            )}
          </TabsContent>
        </Tabs>
      </div>
    </ContentBlock>
  );
}