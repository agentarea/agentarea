"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle
} from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  ArrowLeft,
  BarChart,
  Bot,
  Brain,
  Clock,
  Database,
  Download,
  FileText,
  Layers,
  RefreshCw,
  Share2,
  Loader2,
  AlertTriangle,
  Pause,
  Play,
  X
} from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useState, useEffect, useCallback } from "react";
import { getAgentTaskStatus, pauseAgentTask, resumeAgentTask, cancelAgentTask } from "@/lib/api";
import { toast } from "sonner";

// Types for task data
interface TaskDetail {
  id: string;
  agent_id: string;
  description: string;
  status: string;
  result?: Record<string, unknown>;
  created_at: string;
  execution_id?: string;
  agent_name?: string;
  agent_description?: string;
}

interface TaskStatus {
  task_id: string;
  agent_id: string;
  execution_id: string;
  status: string;
  start_time?: string;
  end_time?: string;
  execution_time?: string;
  error?: string;
  result?: Record<string, unknown>;
  message?: string;
  artifacts?: unknown[];
  session_id?: string;
  usage_metadata?: Record<string, unknown>;
}

export default function TaskDetailsPage() {
  const params = useParams();
  const router = useRouter();
  const id = Array.isArray(params.id) ? params.id[0] : params.id as string;
  const [activeTab, setActiveTab] = useState("overview");
  
  // State for real data
  const [task, setTask] = useState<TaskDetail | null>(null);
  const [taskStatus, setTaskStatus] = useState<TaskStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [controlling, setControlling] = useState(false);
  const [showCancelDialog, setShowCancelDialog] = useState(false);

  const loadTaskData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      // Since we only have the task ID from the URL, we need to find the task
      // by searching through all agents' tasks. This is not ideal but necessary
      // given the current API structure.
      
      // First, get all tasks to find the one with matching ID
      const { getAllTasks } = await import("@/lib/api");
      const { data: allTasks, error: tasksError } = await getAllTasks();
      
      if (tasksError || !allTasks) {
        throw new Error("Failed to load tasks");
      }

      // Find the task with matching ID
      const foundTask = allTasks.find(task => task.id.toString() === id);
      
      if (!foundTask) {
        throw new Error("Task not found");
      }

      // Set basic task data
      setTask({
        id: foundTask.id.toString(),
        agent_id: foundTask.agent_id.toString(),
        description: foundTask.description,
        status: foundTask.status,
        result: foundTask.result,
        created_at: foundTask.created_at,
        execution_id: foundTask.execution_id,
        agent_name: foundTask.agent_name,
        agent_description: foundTask.agent_description,
      });

      // Get detailed status information
      const statusResponse = await getAgentTaskStatus(
        foundTask.agent_id.toString(), 
        foundTask.id.toString()
      );
      
      if (!statusResponse.error && statusResponse.data) {
        setTaskStatus(statusResponse.data as TaskStatus);
      }

    } catch (err) {
      console.error("Failed to load task data:", err);
      setError("Failed to load task details. The task may not exist or you may not have permission to view it.");
    } finally {
      setLoading(false);
    }
  }, [id]);

  // Load task data on mount and when ID changes
  useEffect(() => {
    loadTaskData();
  }, [loadTaskData]);

  const handleRefresh = async () => {
    setRefreshing(true);
    await loadTaskData();
    setRefreshing(false);
  };

  // Task control handlers
  const handlePauseTask = async () => {
    if (!task) return;
    
    try {
      setControlling(true);
      const { error } = await pauseAgentTask(task.agent_id, task.id);
      
      if (error) {
        toast.error("Failed to pause task", {
          description: error.message || "An error occurred while pausing the task"
        });
      } else {
        toast.success("Task paused successfully");
        // Refresh task data to get updated status
        await loadTaskData();
      }
    } catch (err) {
      toast.error("Failed to pause task", {
        description: "An unexpected error occurred"
      });
    } finally {
      setControlling(false);
    }
  };

  const handleResumeTask = async () => {
    if (!task) return;
    
    try {
      setControlling(true);
      const { error } = await resumeAgentTask(task.agent_id, task.id);
      
      if (error) {
        toast.error("Failed to resume task", {
          description: error.message || "An error occurred while resuming the task"
        });
      } else {
        toast.success("Task resumed successfully");
        // Refresh task data to get updated status
        await loadTaskData();
      }
    } catch (err) {
      toast.error("Failed to resume task", {
        description: "An unexpected error occurred"
      });
    } finally {
      setControlling(false);
    }
  };

  const handleCancelTask = async () => {
    if (!task) return;
    
    try {
      setControlling(true);
      const { error } = await cancelAgentTask(task.agent_id, task.id);
      
      if (error) {
        toast.error("Failed to cancel task", {
          description: error.message || "An error occurred while cancelling the task"
        });
      } else {
        toast.success("Task cancelled successfully");
        // Refresh task data to get updated status
        await loadTaskData();
      }
    } catch (err) {
      toast.error("Failed to cancel task", {
        description: "An unexpected error occurred"
      });
    } finally {
      setControlling(false);
      setShowCancelDialog(false);
    }
  };

  // Determine which control buttons to show based on task status
  const getControlButtons = () => {
    if (!isActive) return null;

    const buttons = [];

    if (currentStatus === "running") {
      buttons.push(
        <Button
          key="pause"
          variant="outline"
          className="gap-1"
          onClick={handlePauseTask}
          disabled={controlling}
        >
          <Pause className="h-4 w-4" />
          Pause
        </Button>
      );
    }

    if (currentStatus === "paused") {
      buttons.push(
        <Button
          key="resume"
          variant="outline"
          className="gap-1"
          onClick={handleResumeTask}
          disabled={controlling}
        >
          <Play className="h-4 w-4" />
          Resume
        </Button>
      );
    }

    if (["running", "paused"].includes(currentStatus)) {
      buttons.push(
        <Button
          key="cancel"
          variant="destructive"
          className="gap-1"
          onClick={() => setShowCancelDialog(true)}
          disabled={controlling}
        >
          <X className="h-4 w-4" />
          Cancel
        </Button>
      );
    }

    return buttons;
  };

  // Status badge color
  const getStatusColor = (status: string) => {
    if (status === "running" || status === "completed") return "bg-green-100 text-green-700";
    if (status === "paused") return "bg-yellow-100 text-yellow-700";
    return "bg-red-100 text-red-700";
  };
  
  // Log level color
  const getLogLevelColor = (level: string) => {
    if (level === "success") return "text-green-600";
    if (level === "error") return "text-red-600";
    if (level === "warning") return "text-yellow-600";
    return "text-blue-600";
  };

  // Show loading state
  if (loading) {
    return (
      <div className="p-8">
        <div className="flex items-center gap-2 mb-6">
          <Button 
            variant="outline" 
            size="sm" 
            onClick={() => router.push("/tasks")}
            className="gap-1"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to Tasks
          </Button>
        </div>
        <div className="flex items-center justify-center py-20">
          <div className="text-center">
            <Loader2 className="h-8 w-8 animate-spin mx-auto mb-4" />
            <p className="text-muted-foreground">Loading task details...</p>
          </div>
        </div>
      </div>
    );
  }

  // Show error state
  if (error || !task) {
    return (
      <div className="p-8">
        <div className="flex items-center gap-2 mb-6">
          <Button 
            variant="outline" 
            size="sm" 
            onClick={() => router.push("/tasks")}
            className="gap-1"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to Tasks
          </Button>
        </div>
        <div className="flex items-center justify-center py-20">
          <div className="text-center">
            <AlertTriangle className="h-12 w-12 mx-auto mb-4 text-destructive" />
            <h3 className="text-lg font-semibold mb-2">Task Not Found</h3>
            <p className="text-muted-foreground mb-4">
              {error || "The requested task could not be found."}
            </p>
            <div className="flex gap-2 justify-center">
              <Button onClick={() => router.push("/tasks")} variant="outline">
                Back to Tasks
              </Button>
              <Button onClick={handleRefresh} variant="default">
                Try Again
              </Button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // Determine if task is active based on status
  const isActive = ["running", "paused"].includes(task.status);
  
  // Get current status from taskStatus or fallback to task.status
  const currentStatus = taskStatus?.status || task.status;
  const executionTime = taskStatus?.execution_time || "N/A";
  const startTime = taskStatus?.start_time || task.created_at;
  const endTime = taskStatus?.end_time;
  const errorMessage = taskStatus?.error;

  return (
    <div className="p-8">
      <div className="flex items-center gap-2 mb-6">
        <Button 
          variant="outline" 
          size="sm" 
          onClick={() => router.push("/tasks")}
          className="gap-1"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Tasks
        </Button>
      </div>
      <div className="flex justify-between items-start mb-8">
        <div className="flex items-start gap-4">
          <div className="h-16 w-16 bg-primary/10 rounded-lg flex items-center justify-center">
            <Layers className="h-8 w-8 text-primary" />
          </div>
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-3xl font-bold">{task.description}</h1>
              <Badge className={getStatusColor(currentStatus)}>
                {currentStatus.charAt(0).toUpperCase() + currentStatus.slice(1)}
              </Badge>
            </div>
            <p className="text-lg text-muted-foreground mt-1">Task ID: {task.id}</p>
            <div className="flex gap-4 mt-4">
              <div className="flex items-center gap-1 text-sm text-muted-foreground">
                <Bot className="h-4 w-4" />
                Agent ID: {task.agent_id}
              </div>
              <div className="flex items-center gap-1 text-sm text-muted-foreground">
                <Clock className="h-4 w-4" />
                {isActive ? `Started: ${new Date(startTime).toLocaleString()}` : 
                 endTime ? `Duration: ${executionTime}` : `Created: ${new Date(task.created_at).toLocaleString()}`}
              </div>
              {task.execution_id && (
                <div className="flex items-center gap-1 text-sm text-muted-foreground">
                  <Database className="h-4 w-4" />
                  Execution: {task.execution_id}
                </div>
              )}
            </div>
          </div>
        </div>
        <div className="flex gap-2">
          {/* Task Control Buttons */}
          {getControlButtons()}
          
          <Button 
            variant="outline" 
            className="gap-1"
            onClick={handleRefresh}
            disabled={refreshing}
          >
            <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
          <Button variant="outline" className="gap-1">
            <Download className="h-4 w-4" />
            Export
          </Button>
          <Button variant="outline" className="gap-1">
            <Share2 className="h-4 w-4" />
            Share
          </Button>
        </div>
      </div>
      
      {/* Show error message if present */}
      {errorMessage && (
        <Card className="mb-8 border-destructive">
          <CardContent className="pt-6">
            <div className="flex items-center gap-2 text-destructive">
              <AlertTriangle className="h-5 w-5" />
              <span className="font-medium">Task Error</span>
            </div>
            <p className="text-sm text-muted-foreground mt-2">{errorMessage}</p>
          </CardContent>
        </Card>
      )}

      {/* Show progress for active tasks */}
      {isActive && (
        <Card className="mb-8">
          <CardContent className="pt-6">
            <div className="mb-2">
              <div className="flex justify-between text-sm mb-1">
                <span className="font-medium">
                  {currentStatus === "running" ? "Task is running..." : 
                   currentStatus === "paused" ? "Task is paused" : 
                   "Task status: " + currentStatus}
                </span>
                <span>{taskStatus?.message || "In progress"}</span>
              </div>
              <div className="w-full bg-secondary h-3 rounded-full overflow-hidden">
                <div 
                  className={`h-full rounded-full ${
                    currentStatus === "running" ? "bg-primary" :
                    currentStatus === "paused" ? "bg-yellow-500" :
                    "bg-red-500"
                  }`} 
                  style={{ width: currentStatus === "running" ? "50%" : "25%" }}
                ></div>
              </div>
            </div>
            {taskStatus?.artifacts && taskStatus.artifacts.length > 0 && (
              <div className="flex flex-wrap gap-2 mt-4">
                <p className="text-sm font-medium mr-2">Artifacts:</p>
                {taskStatus.artifacts.map((artifact, index) => (
                  <Badge key={index} variant="secondary">
                    {typeof artifact === 'string' ? artifact : `Artifact ${index + 1}`}
                  </Badge>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}
      <Tabs defaultValue="overview" value={activeTab} className="w-full" onValueChange={setActiveTab}>
        <TabsList className="mb-6">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="logs">Execution Logs</TabsTrigger>
          <TabsTrigger value="artifacts">Artifacts</TabsTrigger>
          <TabsTrigger value="memory">Memory</TabsTrigger>
          <TabsTrigger value="metrics">Metrics</TabsTrigger>
          {isActive && <TabsTrigger value="configuration">Configuration</TabsTrigger>}
        </TabsList>
        <TabsContent value="overview">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <Card>
              <CardHeader>
                <CardTitle>Task Details</CardTitle>
              </CardHeader>
              <CardContent>
                <dl className="space-y-4">
                  <div>
                    <dt className="text-sm font-medium text-muted-foreground">Status</dt>
                    <dd className="mt-1">
                      <Badge className={getStatusColor(currentStatus)}>
                        {currentStatus.charAt(0).toUpperCase() + currentStatus.slice(1)}
                      </Badge>
                    </dd>
                  </div>
                  <div>
                    <dt className="text-sm font-medium text-muted-foreground">Agent</dt>
                    <dd className="mt-1">{task.agent_name || `Agent ${task.agent_id}`}</dd>
                  </div>
                  <div>
                    <dt className="text-sm font-medium text-muted-foreground">Agent Description</dt>
                    <dd className="mt-1">{task.agent_description || "No description available"}</dd>
                  </div>
                  <div>
                    <dt className="text-sm font-medium text-muted-foreground">Execution ID</dt>
                    <dd className="mt-1">
                      <code className="text-xs bg-muted px-2 py-1 rounded">
                        {task.execution_id || "N/A"}
                      </code>
                    </dd>
                  </div>
                  <div>
                    <dt className="text-sm font-medium text-muted-foreground">Created At</dt>
                    <dd className="mt-1">{new Date(task.created_at).toLocaleString()}</dd>
                  </div>
                  {startTime && startTime !== task.created_at && (
                    <div>
                      <dt className="text-sm font-medium text-muted-foreground">Started At</dt>
                      <dd className="mt-1">{new Date(startTime).toLocaleString()}</dd>
                    </div>
                  )}
                  {endTime && (
                    <>
                      <div>
                        <dt className="text-sm font-medium text-muted-foreground">Ended At</dt>
                        <dd className="mt-1">{new Date(endTime).toLocaleString()}</dd>
                      </div>
                      <div>
                        <dt className="text-sm font-medium text-muted-foreground">Duration</dt>
                        <dd className="mt-1">{executionTime}</dd>
                      </div>
                    </>
                  )}
                </dl>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Task Parameters</CardTitle>
                <CardDescription>Parameters and configuration for this task</CardDescription>
              </CardHeader>
              <CardContent>
                {task.result ? (
                  <div className="space-y-4">
                    <div>
                      <h4 className="text-sm font-medium mb-2">Result</h4>
                      <div className="bg-muted rounded-lg p-3 text-sm font-mono max-h-40 overflow-y-auto">
                        <pre>{JSON.stringify(task.result, null, 2)}</pre>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="text-center py-8">
                    <FileText className="h-12 w-12 mx-auto mb-4 text-muted-foreground opacity-50" />
                    <p className="text-muted-foreground">
                      {isActive ? "Task is still running..." : "No result data available"}
                    </p>
                  </div>
                )}
                {taskStatus?.session_id && (
                  <div className="mt-4">
                    <h4 className="text-sm font-medium mb-2">Session ID</h4>
                    <code className="text-xs bg-muted px-2 py-1 rounded">
                      {taskStatus.session_id}
                    </code>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>
        <TabsContent value="logs">
          <Card>
            <CardHeader>
              <CardTitle>Execution Logs</CardTitle>
              <CardDescription>Detailed logs of the task execution</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="bg-muted rounded-lg p-4 font-mono text-sm h-[400px] overflow-y-auto">
                {/* Basic log entries based on task status */}
                <div className="mb-2">
                  <span className="text-muted-foreground">[{new Date(task.created_at).toLocaleString()}]</span>{" "}
                  <span className="text-blue-600">INFO:</span>{" "}
                  Task created: {task.description}
                </div>
                {taskStatus?.start_time && (
                  <div className="mb-2">
                    <span className="text-muted-foreground">[{new Date(taskStatus.start_time).toLocaleString()}]</span>{" "}
                    <span className="text-blue-600">INFO:</span>{" "}
                    Task execution started
                  </div>
                )}
                {taskStatus?.message && (
                  <div className="mb-2">
                    <span className="text-muted-foreground">[{new Date().toLocaleString()}]</span>{" "}
                    <span className="text-blue-600">INFO:</span>{" "}
                    {taskStatus.message}
                  </div>
                )}
                {taskStatus?.error && (
                  <div className="mb-2">
                    <span className="text-muted-foreground">[{new Date().toLocaleString()}]</span>{" "}
                    <span className="text-red-600">ERROR:</span>{" "}
                    {taskStatus.error}
                  </div>
                )}
                {taskStatus?.end_time && (
                  <div className="mb-2">
                    <span className="text-muted-foreground">[{new Date(taskStatus.end_time).toLocaleString()}]</span>{" "}
                    <span className={getLogLevelColor(currentStatus === "completed" ? "success" : "error")}>
                      {currentStatus === "completed" ? "SUCCESS" : "ERROR"}:
                    </span>{" "}
                    Task {currentStatus === "completed" ? "completed successfully" : "execution ended"}
                  </div>
                )}
                {isActive && currentStatus === "running" && (
                  <div className="animate-pulse">
                    <span className="text-muted-foreground">[{new Date().toLocaleString()}]</span>{" "}
                    <span className="text-blue-600">INFO:</span>{" "}
                    Task is currently running...
                  </div>
                )}
                {!isActive && !taskStatus?.end_time && (
                  <div className="text-center py-8 text-muted-foreground">
                    <FileText className="h-8 w-8 mx-auto mb-2 opacity-50" />
                    <p>No detailed execution logs available</p>
                    <p className="text-xs mt-1">Logs will be available in future versions</p>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="metrics">
          <Card>
            <CardHeader>
              <CardTitle>Performance Metrics</CardTitle>
              <CardDescription>Key metrics for this task execution</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                <div className="bg-muted rounded-lg p-4">
                  <div className="text-sm text-muted-foreground mb-1">Execution Time</div>
                  <div className="text-2xl font-bold">{executionTime}</div>
                </div>
                <div className="bg-muted rounded-lg p-4">
                  <div className="text-sm text-muted-foreground mb-1">Status</div>
                  <div className="text-2xl font-bold">{currentStatus}</div>
                </div>
                <div className="bg-muted rounded-lg p-4">
                  <div className="text-sm text-muted-foreground mb-1">Execution ID</div>
                  <div className="text-lg font-bold truncate">{task.execution_id || "N/A"}</div>
                </div>
                <div className="bg-muted rounded-lg p-4">
                  <div className="text-sm text-muted-foreground mb-1">Usage Data</div>
                  <div className="text-2xl font-bold">
                    {taskStatus?.usage_metadata ? "Available" : "N/A"}
                  </div>
                </div>
              </div>
              {taskStatus?.usage_metadata && (
                <div className="mt-6">
                  <h4 className="text-sm font-medium mb-2">Usage Metadata</h4>
                  <div className="bg-muted rounded-lg p-3 text-sm font-mono max-h-40 overflow-y-auto">
                    <pre>{JSON.stringify(taskStatus.usage_metadata, null, 2)}</pre>
                  </div>
                </div>
              )}
              <div className="mt-8 flex justify-center">
                <div className="text-center text-muted-foreground">
                  <BarChart className="h-32 w-32 mx-auto mb-4 opacity-50" />
                  <p>Detailed performance charts will be available in future versions</p>
                  <p className="text-xs mt-1">Metrics are collected from Temporal workflow execution</p>
                </div>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="artifacts">
          <Card>
            <CardHeader>
              <CardTitle>Artifacts</CardTitle>
              <CardDescription>Files and outputs generated by this task</CardDescription>
            </CardHeader>
            <CardContent>
              {taskStatus?.artifacts && taskStatus.artifacts.length > 0 ? (
                <div className="space-y-4">
                  {taskStatus.artifacts.map((artifact, index) => (
                    <div key={index} className="flex items-center justify-between p-4 border rounded-lg">
                      <div className="flex items-center gap-3">
                        <FileText className="h-8 w-8 text-primary" />
                        <div>
                          <p className="font-medium">
                            {typeof artifact === 'string' ? artifact : `Artifact ${index + 1}`}
                          </p>
                          <p className="text-sm text-muted-foreground">
                            Generated by task execution
                          </p>
                        </div>
                      </div>
                      <Button variant="outline" size="sm" className="gap-1" disabled>
                        <Download className="h-4 w-4" />
                        Download
                      </Button>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-center py-12">
                  <FileText className="h-16 w-16 mx-auto mb-4 text-muted-foreground opacity-50" />
                  <h3 className="text-lg font-semibold mb-2">No Artifacts</h3>
                  <p className="text-muted-foreground">
                    {isActive ? "Artifacts will appear here as the task generates outputs." : "This task did not generate any artifacts."}
                  </p>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="memory">
          <Card>
            <CardHeader>
              <CardTitle>Memory Context</CardTitle>
              <CardDescription>Current memory state and context information</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="text-center py-12">
                <Brain className="h-16 w-16 mx-auto mb-4 text-muted-foreground opacity-50" />
                <h3 className="text-lg font-semibold mb-2">Memory Context</h3>
                <p className="text-muted-foreground mb-4">
                  Memory context information is not yet available through the current API.
                </p>
                <p className="text-xs text-muted-foreground">
                  This feature will be implemented in future versions to show task memory state and context.
                </p>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
        {isActive && (
          <TabsContent value="configuration">
            <Card>
              <CardHeader>
                <CardTitle>Task Configuration</CardTitle>
                <CardDescription>Settings and parameters for this task execution</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="text-center py-12">
                  <Database className="h-16 w-16 mx-auto mb-4 text-muted-foreground opacity-50" />
                  <h3 className="text-lg font-semibold mb-2">Task Configuration</h3>
                  <p className="text-muted-foreground mb-4">
                    Task configuration details are not yet available through the current API.
                  </p>
                  <p className="text-xs text-muted-foreground">
                    Configuration settings will be displayed here in future versions.
                  </p>
                </div>
              </CardContent>
            </Card>
          </TabsContent>
        )}
      </Tabs>

      {/* Cancel Confirmation Dialog */}
      <Dialog open={showCancelDialog} onOpenChange={setShowCancelDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Cancel Task</DialogTitle>
            <DialogDescription>
              Are you sure you want to cancel this task? This action cannot be undone and will terminate the task execution immediately.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setShowCancelDialog(false)}
              disabled={controlling}
            >
              Keep Running
            </Button>
            <Button
              variant="destructive"
              onClick={handleCancelTask}
              disabled={controlling}
            >
              {controlling ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  Cancelling...
                </>
              ) : (
                <>
                  <X className="h-4 w-4 mr-2" />
                  Cancel Task
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}