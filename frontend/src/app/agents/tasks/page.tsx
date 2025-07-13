"use client";

import React, { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import {
  Bot,
  Calendar,
  Download,
  RefreshCw,
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

// Enhanced task type with agent information
interface TaskWithAgent extends TaskResponse {
  agent_name?: string;
  agent_description?: string;
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

export default function TasksPage() {
  const [activeTab, setActiveTab] = useState("active");
  const [tasks, setTasks] = useState<TaskWithAgent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  // Load tasks on mount
  useEffect(() => {
    loadTasks();
  }, []);

  const loadTasks = async () => {
    try {
      setLoading(true);
      setError(null);
      const { data: tasksData, error: tasksError } = await getAllTasks();
      
      if (tasksError) {
        setError("Failed to load tasks");
      } else {
        setTasks(tasksData || []);
      }
    } catch (err) {
      setError("Failed to load tasks");
    } finally {
      setLoading(false);
    }
  };

  const handleRefresh = () => {
    loadTasks();
  };
  
  const navigateToDetails = (id: string) => {
    router.push(`/agents/tasks/${id}`);
  };

  // Filter tasks by status
  const activeTasks = tasks.filter(task => 
    task.status === "running" || task.status === "paused" || task.status === "error"
  );
  
  const completedTasks = tasks.filter(task => 
    task.status === "completed" || task.status === "success" || task.status === "failed"
  );

  return (
    <ContentBlock
      header={{
        title: "Agent Workflows",
        description: "Monitor, manage, and review your agent workflows",
        controls: (
          <div className="flex gap-4">
            {activeTab === "active" ? (
              <>
                <Button
                  variant="outline"
                  onClick={handleRefresh}
                  disabled={loading}
                  className="gap-2"
                >
                  <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
                  Refresh
                </Button>
                <Button
                  onClick={() => router.push('/agents/create')}
                  className="gap-2"
                >
                  <Bot className="h-5 w-5" />
                  Deploy New Agent
                </Button>
              </>
            ) : (
              <>
                <Button variant="outline" disabled className="gap-2">
                  <Calendar className="h-4 w-4" />
                  Date Range
                </Button>
                <Button variant="outline" disabled className="gap-2">
                  <Download className="h-4 w-4" />
                  Export
                </Button>
              </>
            )}
          </div>
        )
      }}
    >
      <>
      <Tabs defaultValue="active" className="w-full" onValueChange={setActiveTab}>
        <TabsList className="mb-6">
          <TabsTrigger value="active">Active Tasks</TabsTrigger>
          <TabsTrigger value="completed">Completed Tasks</TabsTrigger>
        </TabsList>

        <TabsContent value="active">
          {loading ? (
            <div className="text-center py-10">
              <Loader2 className="h-8 w-8 animate-spin mx-auto mb-4" />
              <p className="text-muted-foreground">Loading tasks...</p>
            </div>
          ) : error ? (
            <div className="text-center py-10">
              <XCircle className="h-8 w-8 mx-auto mb-4 text-destructive" />
              <p className="text-destructive mb-4">{error}</p>
              <Button onClick={handleRefresh} variant="outline">
                Try Again
              </Button>
            </div>
          ) : activeTasks.length === 0 ? (
            <div className="text-center py-10">
              <Bot className="h-12 w-12 mx-auto mb-4 text-muted-foreground" />
              <h3 className="text-lg font-semibold mb-2">No active tasks</h3>
              <p className="text-muted-foreground mb-4">
                There are currently no active tasks running. Create a new task to get started.
              </p>
              <Button onClick={() => router.push('/agents/create')}>
                Deploy New Agent
              </Button>
            </div>
          ) : (
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
                  {activeTasks.map((task) => (
                    <TableRow 
                      key={task.id}
                      className="cursor-pointer hover:bg-muted/50"
                      onClick={() => navigateToDetails(task.id.toString())}
                    >
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
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </TabsContent>

        <TabsContent value="completed">
          {loading ? (
            <div className="text-center py-10">
              <Loader2 className="h-8 w-8 animate-spin mx-auto mb-4" />
              <p className="text-muted-foreground">Loading completed tasks...</p>
            </div>
          ) : error ? (
            <div className="text-center py-10">
              <XCircle className="h-8 w-8 mx-auto mb-4 text-destructive" />
              <p className="text-destructive mb-4">{error}</p>
              <Button onClick={handleRefresh} variant="outline">
                Try Again
              </Button>
            </div>
          ) : completedTasks.length === 0 ? (
            <div className="text-center py-10">
              <CheckCircle2 className="h-12 w-12 mx-auto mb-4 text-muted-foreground" />
              <h3 className="text-lg font-semibold mb-2">No completed tasks</h3>
              <p className="text-muted-foreground">
                Completed tasks will appear here once they finish execution.
              </p>
            </div>
          ) : (
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
                  {completedTasks.map((task) => (
                    <TableRow 
                      key={task.id}
                      className="cursor-pointer hover:bg-muted/50"
                      onClick={() => navigateToDetails(task.id.toString())}
                    >
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
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </TabsContent>
      </Tabs>
    </>
    </ContentBlock>
  );
} 