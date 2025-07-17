"use client";

import React, { useState, useEffect, useMemo } from "react";
import { useRouter, useSearchParams } from "next/navigation";
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
  Search,
  Filter,
  X,
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
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { getAllTasks, type TaskResponse } from "@/lib/api";

// Enhanced task type with agent information
interface TaskWithAgent extends TaskResponse {
  agent_name?: string;
  agent_description?: string | null;
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

// Define all possible task statuses
const TASK_STATUSES = [
  "running",
  "completed", 
  "success",
  "failed",
  "error",
  "paused",
  "pending",
  "cancelled"
] as const;

export default function TasksPage() {
  const [activeTab, setActiveTab] = useState("active");
  const [tasks, setTasks] = useState<TaskWithAgent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();
  const searchParams = useSearchParams();

  // Filter states with URL persistence
  const [searchQuery, setSearchQuery] = useState(searchParams.get("search") || "");
  const [statusFilter, setStatusFilter] = useState(searchParams.get("status") || "all");

  // Load tasks on mount
  useEffect(() => {
    loadTasks();
  }, []);

  // Update URL when filters change
  useEffect(() => {
    const params = new URLSearchParams();
    if (searchQuery) params.set("search", searchQuery);
    if (statusFilter !== "all") params.set("status", statusFilter);
    
    const newUrl = params.toString() ? `?${params.toString()}` : "";
    router.replace(`/agents/tasks${newUrl}`, { scroll: false });
  }, [searchQuery, statusFilter, router]);

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
    } catch {
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

  // Clear all filters
  const clearFilters = () => {
    setSearchQuery("");
    setStatusFilter("all");
  };

  // Filter tasks based on search query and status filter
  const filteredTasks = useMemo(() => {
    let filtered = tasks;

    // Apply search filter
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      filtered = filtered.filter(task => 
        task.description.toLowerCase().includes(query) ||
        (task.agent_name && task.agent_name.toLowerCase().includes(query))
      );
    }

    // Apply status filter
    if (statusFilter !== "all") {
      filtered = filtered.filter(task => task.status === statusFilter);
    }

    return filtered;
  }, [tasks, searchQuery, statusFilter]);

  // Filter tasks by tab (active vs completed) from the filtered results
  const activeTasks = filteredTasks.filter(task => 
    task.status === "running" || task.status === "paused" || task.status === "error"
  );
  
  const completedTasks = filteredTasks.filter(task => 
    task.status === "completed" || task.status === "success" || task.status === "failed"
  );

  // Check if any filters are active
  const hasActiveFilters = searchQuery.trim() !== "" || statusFilter !== "all";

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
      {/* Filter Controls */}
      <div className="flex flex-col sm:flex-row gap-4 mb-6">
        <div className="flex-1 relative">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search tasks by description or agent name..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-10"
          />
        </div>
        <div className="flex gap-2">
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="w-[180px]">
              <Filter className="h-4 w-4 mr-2" />
              <SelectValue placeholder="Filter by status" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Statuses</SelectItem>
              {TASK_STATUSES.map((status) => (
                <SelectItem key={status} value={status}>
                  {status.charAt(0).toUpperCase() + status.slice(1)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {hasActiveFilters && (
            <Button
              variant="outline"
              size="sm"
              onClick={clearFilters}
              className="gap-1"
            >
              <X className="h-4 w-4" />
              Clear
            </Button>
          )}
        </div>
      </div>

      <Tabs defaultValue="active" className="w-full" onValueChange={setActiveTab}>
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
              {hasActiveFilters ? (
                <>
                  <Search className="h-12 w-12 mx-auto mb-4 text-muted-foreground" />
                  <h3 className="text-lg font-semibold mb-2">No matching active tasks</h3>
                  <p className="text-muted-foreground mb-4">
                    No active tasks match your current filters. Try adjusting your search or status filter.
                  </p>
                  <Button onClick={clearFilters} variant="outline">
                    Clear Filters
                  </Button>
                </>
              ) : (
                <>
                  <Bot className="h-12 w-12 mx-auto mb-4 text-muted-foreground" />
                  <h3 className="text-lg font-semibold mb-2">No active tasks</h3>
                  <p className="text-muted-foreground mb-4">
                    There are currently no active tasks running. Create a new task to get started.
                  </p>
                  <Button onClick={() => router.push('/agents/create')}>
                    Deploy New Agent
                  </Button>
                </>
              )}
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
              {hasActiveFilters ? (
                <>
                  <Search className="h-12 w-12 mx-auto mb-4 text-muted-foreground" />
                  <h3 className="text-lg font-semibold mb-2">No matching completed tasks</h3>
                  <p className="text-muted-foreground mb-4">
                    No completed tasks match your current filters. Try adjusting your search or status filter.
                  </p>
                  <Button onClick={clearFilters} variant="outline">
                    Clear Filters
                  </Button>
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