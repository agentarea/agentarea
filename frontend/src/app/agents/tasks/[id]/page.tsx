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
  ArrowLeft,
  BarChart,
  Bot,
  Brain,
  Calendar,
  Clock,
  Database,
  Download,
  FileText,
  Layers,
  Pause,
  Play,
  RefreshCw,
  Share2,
  XCircle
} from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

// Mock data for the task details
// In a real application, this would be fetched from an API based on the ID
const getTaskDetails = (id: string) => {
  // Active task example
  if (id === "agent-1" || id === "agent-2" || id === "agent-3" || id === "agent-4")
    return {
      id,
      taskName: id === "agent-1" ? "Inventory Monitoring Task" : 
            id === "agent-2" ? "Support Ticket Routing Task" : 
            id === "agent-3" ? "Analytics Reporting Task" : "Data Sync Task",
      agentName: id === "agent-1" ? "Inventory Monitor" : 
            id === "agent-2" ? "Support Ticket Router" : 
            id === "agent-3" ? "Analytics Reporter" : "Data Sync Agent",
      description: id === "agent-1" ? "Monitoring stock levels across all warehouses" :
                  id === "agent-2" ? "Processing and routing customer support tickets" :
                  id === "agent-3" ? "Generating daily analytics reports" : 
                  "Synchronizing data between systems",
      status: id === "agent-1" || id === "agent-2" ? "running" : 
              id === "agent-3" ? "paused" : "error",
      startTime: "2024-02-24 09:30:00",
      currentStep: id === "agent-1" ? "Analyzing inventory data" :
                  id === "agent-2" ? "Classifying ticket priority" :
                  id === "agent-3" ? "Waiting for data source connection" :
                  "Failed at authentication step",
      progress: id === "agent-1" ? 65 : 
                id === "agent-2" ? 80 : 
                id === "agent-3" ? 25 : 10,
      toolsUsed: id === "agent-1" ? ["Database Query", "Data Analysis", "Notification"] :
                id === "agent-2" ? ["NLP Processing", "Ticket API", "Team Assignment"] :
                id === "agent-3" ? ["Data Connector", "Chart Generation"] :
                ["API Authentication", "Data Transfer"],
      lastActivity: id === "agent-1" ? "2 minutes ago" :
                   id === "agent-2" ? "30 seconds ago" :
                   id === "agent-3" ? "1 hour ago" : "5 minutes ago",
      type: id === "agent-1" ? "E-commerce" :
            id === "agent-2" ? "Support" :
            id === "agent-3" ? "Analytics" : "Integration",
      executionLogs: [
        { timestamp: "2024-02-24 09:30:00", message: "Task started", level: "info" },
        { timestamp: "2024-02-24 09:30:05", message: "Connecting to data sources", level: "info" },
        { timestamp: "2024-02-24 09:30:10", message: "Successfully connected to primary database", level: "success" },
        { timestamp: "2024-02-24 09:31:00", message: "Fetching inventory data", level: "info" },
        { timestamp: "2024-02-24 09:32:00", message: "Processing inventory levels", level: "info" },
        { timestamp: "2024-02-24 09:33:00", message: "Analyzing stock trends", level: "info" },
        { timestamp: "2024-02-24 09:34:00", message: "Generating inventory report", level: "info" },
        { timestamp: id === "agent-4" ? "2024-02-24 09:34:30" : "", message: id === "agent-4" ? "Authentication failed: Invalid credentials" : "", level: id === "agent-4" ? "error" : "info" },
      ].filter(log => log.message !== ""),
      metrics: {
        executionTime: "10m 30s",
        dataProcessed: "1.2 GB",
        apiCalls: 45,
        successRate: id === "agent-4" ? "10%" : "98%"
      },
      memory: {
        contextSize: "2.4 MB",
        keyItems: [
          { key: "inventory_levels", value: "JSON object with current stock levels", type: "object" },
          { key: "historical_data", value: "Last 30 days of inventory movement", type: "array" },
          { key: "threshold_rules", value: "Rules for triggering alerts", type: "object" }
        ],
        lastUpdated: "2 minutes ago"
      },
      artifacts: [
        { name: "inventory_report.pdf", type: "PDF", size: "245 KB", created: "5 minutes ago" },
        { name: "stock_alerts.json", type: "JSON", size: "12 KB", created: "2 minutes ago" },
        { name: "trend_analysis.csv", type: "CSV", size: "78 KB", created: "3 minutes ago" }
      ],
      configuration: {
        schedule: "Every 6 hours",
        timeout: "30 minutes",
        retryPolicy: "3 attempts with exponential backoff",
        notificationSettings: "Email on failure"
      }
    };
  
  // Completed task example
  return {
    id,
    taskName: id === "run-1" ? "Inventory Monitoring Task" : 
          id === "run-2" ? "Support Ticket Routing Task" : 
          id === "run-3" ? "Analytics Reporting Task" : "Data Sync Task",
    agentName: id === "run-1" ? "Inventory Monitor" : 
          id === "run-2" ? "Support Ticket Router" : 
          id === "run-3" ? "Analytics Reporter" : "Data Sync Agent",
    description: id === "run-1" ? "Monitoring stock levels across all warehouses" :
                id === "run-2" ? "Processing and routing customer support tickets" :
                id === "run-3" ? "Generating daily analytics reports" : 
                "Synchronizing data between systems",
    status: id === "run-1" || id === "run-4" ? "success" : 
            id === "run-2" ? "warning" : "failed",
    startTime: "2024-02-10 14:30:00",
    endTime: "2024-02-10 14:35:30",
    duration: id === "run-1" ? "5m 30s" :
              id === "run-2" ? "2m 45s" :
              id === "run-3" ? "1m 15s" : "8m 20s",
    outcome: id === "run-1" ? "Stock levels checked, no alerts needed" :
             id === "run-2" ? "Processed 15 tickets, 2 required manual review" :
             id === "run-3" ? "Failed to connect to data source" : 
             "Successfully synced 1,234 records",
    toolsUsed: id === "run-1" ? ["Database Query", "Data Analysis", "Notification"] :
              id === "run-2" ? ["NLP Processing", "Ticket API", "Team Assignment"] :
              id === "run-3" ? ["Data Connector"] :
              ["API Authentication", "Data Transfer", "Validation"],
    type: id === "run-1" ? "Scheduled" :
          id === "run-2" ? "Event Triggered" :
          id === "run-3" ? "Manual" : "Scheduled",
    executionLogs: [
      { timestamp: "2024-02-10 14:30:00", message: "Task started", level: "info" },
      { timestamp: "2024-02-10 14:30:05", message: "Connecting to data sources", level: "info" },
      { timestamp: "2024-02-10 14:30:10", message: "Successfully connected to primary database", level: "success" },
      { timestamp: "2024-02-10 14:31:00", message: "Fetching inventory data", level: "info" },
      { timestamp: "2024-02-10 14:32:00", message: "Processing inventory levels", level: "info" },
      { timestamp: "2024-02-10 14:33:00", message: "Analyzing stock trends", level: "info" },
      { timestamp: "2024-02-10 14:34:00", message: "Generating inventory report", level: "info" },
      { timestamp: "2024-02-10 14:35:30", message: id === "run-3" ? "Failed to connect to data source: Timeout" : "Task completed successfully", level: id === "run-3" ? "error" : "success" },
    ],
    metrics: {
      executionTime: id === "run-1" ? "5m 30s" :
                    id === "run-2" ? "2m 45s" :
                    id === "run-3" ? "1m 15s" : "8m 20s",
      dataProcessed: id === "run-1" ? "250 MB" :
                    id === "run-2" ? "15 tickets" :
                    id === "run-3" ? "0 MB" : "1.5 GB",
      apiCalls: id === "run-1" ? 12 :
               id === "run-2" ? 30 :
               id === "run-3" ? 2 : 45,
      successRate: id === "run-1" || id === "run-4" ? "100%" : 
                  id === "run-2" ? "87%" : "0%"
    },
    memory: {
      contextSize: "1.8 MB",
      keyItems: [
        { key: "inventory_levels", value: "JSON object with final stock levels", type: "object" },
        { key: "historical_data", value: "Last 30 days of inventory movement", type: "array" },
        { key: "threshold_rules", value: "Rules for triggering alerts", type: "object" }
      ],
      lastUpdated: "2024-02-10 14:35:30"
    },
  };
};

export default function TaskDetailsPage() {
  const params = useParams();
  const router = useRouter();
  const id = Array.isArray(params.id) ? params.id[0] : params.id as string;
  const [activeTab, setActiveTab] = useState("overview");
  
  const task = getTaskDetails(id);
  const isActive = !("endTime" in task);
  
  // Status badge color
  const getStatusColor = (status: string) => {
    if (status === "running" || status === "success") return "bg-green-100 text-green-700";
    if (status === "paused" || status === "warning") return "bg-yellow-100 text-yellow-700";
    return "bg-red-100 text-red-700";
  };
  
  // Log level color
  const getLogLevelColor = (level: string) => {
    if (level === "success") return "text-green-600";
    if (level === "error") return "text-red-600";
    if (level === "warning") return "text-yellow-600";
    return "text-blue-600";
  };

  return (
    <div className="p-8">
      <div className="flex items-center gap-2 mb-6">
        <Button 
          variant="outline" 
          size="sm" 
          onClick={() => router.push("/agents/tasks")}
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
              <h1 className="text-3xl font-bold">{task.taskName}</h1>
              <Badge className={getStatusColor(task.status)}>
                {task.status.charAt(0).toUpperCase() + task.status.slice(1)}
              </Badge>
            </div>
            <p className="text-lg text-muted-foreground mt-1">{task.description}</p>
            <div className="flex gap-4 mt-4">
              <div className="flex items-center gap-1 text-sm text-muted-foreground">
                <Bot className="h-4 w-4" />
                Agent: {task.agentName}
              </div>
              <div className="flex items-center gap-1 text-sm text-muted-foreground">
                <Clock className="h-4 w-4" />
                {isActive ? `Started: ${task.startTime}` : `Duration: ${task.duration}`}
              </div>
              <div className="flex items-center gap-1 text-sm text-muted-foreground">
                <Calendar className="h-4 w-4" />
                Type: {task.type}
              </div>
            </div>
          </div>
        </div>
        <div className="flex gap-2">
          {isActive && (
            <>
              {task.status === "running" ? (
                <Button variant="outline" className="gap-1">
                  <Pause className="h-4 w-4" />
                  Pause
                </Button>
              ) : task.status === "paused" ? (
                <Button variant="outline" className="gap-1">
                  <Play className="h-4 w-4" />
                  Resume
                </Button>
              ) : null}
              <Button variant="outline" className="gap-1">
                <XCircle className="h-4 w-4" />
                Stop
              </Button>
              <Button variant="outline" className="gap-1">
                <RefreshCw className="h-4 w-4" />
                Refresh
              </Button>
            </>
          )}
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
      {isActive && (
        <Card className="mb-8">
          <CardContent className="pt-6">
            <div className="mb-2">
              <div className="flex justify-between text-sm mb-1">
                <span className="font-medium">{task.currentStep}</span>
                <span>{task.progress}%</span>
              </div>
              <div className="w-full bg-secondary h-3 rounded-full overflow-hidden">
                <div 
                  className={`h-full rounded-full ${
                    task.status === "running" ? "bg-primary" :
                    task.status === "paused" ? "bg-yellow-500" :
                    "bg-red-500"
                  }`} 
                  style={{ width: `${task.progress}%` }}
                ></div>
              </div>
            </div>
            <div className="flex flex-wrap gap-2 mt-4">
              <p className="text-sm font-medium mr-2">Tools Used:</p>
              {task.toolsUsed.map((tool, index) => (
                <Badge key={index} variant="secondary">
                  {tool}
                </Badge>
              ))}
            </div>
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
                      <Badge className={getStatusColor(task.status)}>
                        {task.status.charAt(0).toUpperCase() + task.status.slice(1)}
                      </Badge>
                    </dd>
                  </div>
                  <div>
                    <dt className="text-sm font-medium text-muted-foreground">Agent</dt>
                    <dd className="mt-1">{task.agentName}</dd>
                  </div>
                  <div>
                    <dt className="text-sm font-medium text-muted-foreground">Type</dt>
                    <dd className="mt-1">{task.type}</dd>
                  </div>
                  {isActive ? (
                    <div>
                      <dt className="text-sm font-medium text-muted-foreground">Started At</dt>
                      <dd className="mt-1">{task.startTime}</dd>
                    </div>
                  ) : (
                    <>
                      <div>
                        <dt className="text-sm font-medium text-muted-foreground">Started At</dt>
                        <dd className="mt-1">{task.startTime}</dd>
                      </div>
                      <div>
                        <dt className="text-sm font-medium text-muted-foreground">Ended At</dt>
                        <dd className="mt-1">{task.endTime}</dd>
                      </div>
                      <div>
                        <dt className="text-sm font-medium text-muted-foreground">Duration</dt>
                        <dd className="mt-1">{task.duration}</dd>
                      </div>
                    </>
                  )}
                </dl>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Tools Used</CardTitle>
                <CardDescription>Tools and capabilities utilized in this task</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="flex flex-wrap gap-2">
                  {task.toolsUsed.map((tool, index) => (
                    <Badge key={index} variant="outline" className="px-3 py-1">
                      {tool}
                    </Badge>
                  ))}
                </div>
                {!isActive && (
                  <div className="mt-6">
                    <h4 className="text-sm font-medium mb-2">Outcome</h4>
                    <p className="text-sm text-muted-foreground">{task.outcome}</p>
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
                {task.executionLogs.map((log, index) => (
                  <div key={index} className="mb-2">
                    <span className="text-muted-foreground">[{log.timestamp}]</span>{" "}
                    <span className={getLogLevelColor(log.level)}>
                      {log.level.toUpperCase()}:
                    </span>{" "}
                    {log.message}
                  </div>
                ))}
                {isActive && task.status === "running" && (
                  <div className="animate-pulse">
                    <span className="text-muted-foreground">[{new Date().toLocaleString()}]</span>{" "}
                    <span className="text-blue-600">INFO:</span>{" "}
                    Waiting for next operation...
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
                  <div className="text-2xl font-bold">{task.metrics.executionTime}</div>
                </div>
                <div className="bg-muted rounded-lg p-4">
                  <div className="text-sm text-muted-foreground mb-1">Data Processed</div>
                  <div className="text-2xl font-bold">{task.metrics.dataProcessed}</div>
                </div>
                <div className="bg-muted rounded-lg p-4">
                  <div className="text-sm text-muted-foreground mb-1">API Calls</div>
                  <div className="text-2xl font-bold">{task.metrics.apiCalls}</div>
                </div>
                <div className="bg-muted rounded-lg p-4">
                  <div className="text-sm text-muted-foreground mb-1">Success Rate</div>
                  <div className="text-2xl font-bold">{task.metrics.successRate}</div>
                </div>
              </div>
              <div className="mt-8 flex justify-center">
                <div className="text-center text-muted-foreground">
                  <BarChart className="h-32 w-32 mx-auto mb-4 opacity-50" />
                  <p>Detailed performance charts will be available here</p>
                </div>
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
                <dl className="space-y-4">
                  {task.configuration && (
                    <>
                      <div>
                        <dt className="text-sm font-medium text-muted-foreground">Schedule</dt>
                        <dd className="mt-1">{task.configuration.schedule}</dd>
                      </div>
                      <div>
                        <dt className="text-sm font-medium text-muted-foreground">Timeout</dt>
                        <dd className="mt-1">{task.configuration.timeout}</dd>
                      </div>
                      <div>
                        <dt className="text-sm font-medium text-muted-foreground">Retry Policy</dt>
                        <dd className="mt-1">{task.configuration.retryPolicy}</dd>
                      </div>
                      <div>
                        <dt className="text-sm font-medium text-muted-foreground">Notification Settings</dt>
                        <dd className="mt-1">{task.configuration.notificationSettings}</dd>
                      </div>
                    </>
                  )}
                </dl>
              </CardContent>
            </Card>
          </TabsContent>
        )}
      </Tabs>
    </div>
  );
}