"use client";

import React, { useState } from "react";
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

// Types for active workflows (previously running agents)
interface ActiveWorkflow {
  id: string;
  name: string;
  description: string;
  status: "running" | "paused" | "error";
  startTime: string;
  currentStep: string;
  progress: number;
  toolsUsed: string[];
  lastActivity: string;
  type: string;
}

// Types for completed workflows (previously agent history)
interface CompletedWorkflow {
  id: string;
  agentName: string;
  status: "success" | "failed" | "warning";
  startTime: string;
  duration: string;
  outcome: string;
  type: string;
  toolsUsed: string[];
}

// Sample data for active workflows
const activeWorkflows: ActiveWorkflow[] = [
  {
    id: "agent-1",
    name: "Inventory Monitor",
    description: "Monitoring stock levels across all warehouses",
    status: "running",
    startTime: "2024-02-24 09:30:00",
    currentStep: "Analyzing inventory data",
    progress: 65,
    toolsUsed: ["Database Query", "Data Analysis", "Notification"],
    lastActivity: "2 minutes ago",
    type: "E-commerce"
  },
  {
    id: "agent-2",
    name: "Support Ticket Router",
    description: "Processing and routing customer support tickets",
    status: "running",
    startTime: "2024-02-24 08:15:00",
    currentStep: "Classifying ticket priority",
    progress: 80,
    toolsUsed: ["NLP Processing", "Ticket API", "Team Assignment"],
    lastActivity: "30 seconds ago",
    type: "Support"
  },
  {
    id: "agent-3",
    name: "Analytics Reporter",
    description: "Generating daily analytics reports",
    status: "paused",
    startTime: "2024-02-24 07:45:00",
    currentStep: "Waiting for data source connection",
    progress: 25,
    toolsUsed: ["Data Connector", "Chart Generation"],
    lastActivity: "1 hour ago",
    type: "Analytics"
  },
  {
    id: "agent-4",
    name: "Data Sync Agent",
    description: "Synchronizing data between systems",
    status: "error",
    startTime: "2024-02-24 10:05:00",
    currentStep: "Failed at authentication step",
    progress: 10,
    toolsUsed: ["API Authentication", "Data Transfer"],
    lastActivity: "5 minutes ago",
    type: "Integration"
  }
];

// Sample data for completed workflows
const completedWorkflows: CompletedWorkflow[] = [
  {
    id: "run-1",
    agentName: "Inventory Monitor",
    status: "success",
    startTime: "2024-02-10 14:30:00",
    duration: "5m 30s",
    outcome: "Stock levels checked, no alerts needed",
    type: "Scheduled",
    toolsUsed: ["Database Query", "Data Analysis", "Notification"]
  },
  {
    id: "run-2",
    agentName: "Support Ticket Router",
    status: "warning",
    startTime: "2024-02-10 14:15:00",
    duration: "2m 45s",
    outcome: "Processed 15 tickets, 2 required manual review",
    type: "Event Triggered",
    toolsUsed: ["NLP Processing", "Ticket API", "Team Assignment"]
  },
  {
    id: "run-3",
    agentName: "Analytics Reporter",
    status: "failed",
    startTime: "2024-02-10 14:00:00",
    duration: "1m 15s",
    outcome: "Failed to connect to data source",
    type: "Manual",
    toolsUsed: ["Data Connector"]
  },
  {
    id: "run-4",
    agentName: "Data Sync Agent",
    status: "success",
    startTime: "2024-02-10 13:45:00",
    duration: "8m 20s",
    outcome: "Successfully synced 1,234 records",
    type: "Scheduled",
    toolsUsed: ["API Authentication", "Data Transfer", "Validation"]
  }
];

const statusIcons = {
  success: <CheckCircle2 className="h-5 w-5 text-green-500" />,
  warning: <AlertTriangle className="h-5 w-5 text-yellow-500" />,
  failed: <XCircle className="h-5 w-5 text-red-500" />
};

export default function WorkflowsPage() {
  const [activeTab, setActiveTab] = useState("active");
  const router = useRouter();
  
  const navigateToDetails = (id: string) => {
    router.push(`/agents/workflows/${id}`);
  };

  return (
    <ContentBlock
      header={{
        title: "Agent Workflows",
        description: "Monitor, manage, and review your agent workflows",
        controls: (
          <div className="flex gap-4">
            {activeTab === "active" ? (
              <>
                <button className="px-4 py-2 border rounded-lg flex items-center gap-2 hover:bg-secondary">
                  <RefreshCw className="h-4 w-4" />
                  Refresh
                </button>
                <button className="bg-primary text-primary-foreground hover:bg-primary/90 px-4 py-2 rounded-lg flex items-center gap-2">
                  <Bot className="h-5 w-5" />
                  Deploy New Agent
                </button>
              </>
            ) : (
              <>
                <button className="px-4 py-2 border rounded-lg flex items-center gap-2 hover:bg-secondary">
                  <Calendar className="h-4 w-4" />
                  Date Range
                </button>
                <button className="px-4 py-2 border rounded-lg flex items-center gap-2 hover:bg-secondary">
                  <Download className="h-4 w-4" />
                  Export
                </button>
              </>
            )}
          </div>
        )
      }}
    >
      <>
      <Tabs defaultValue="active" className="w-full" onValueChange={setActiveTab}>
        <TabsList className="mb-6">
          <TabsTrigger value="active">Active Workflows</TabsTrigger>
          <TabsTrigger value="completed">Completed Workflows</TabsTrigger>
        </TabsList>

        <TabsContent value="active">
          <div className="rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Progress</TableHead>
                  <TableHead>Current Step</TableHead>
                  <TableHead>Start Time</TableHead>
                  <TableHead>Last Activity</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Tools</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {activeWorkflows.map((workflow) => (
                  <TableRow 
                    key={workflow.id}
                    className="cursor-pointer hover:bg-muted/50"
                    onClick={() => navigateToDetails(workflow.id)}
                  >
                    <TableCell className="font-medium">
                      <div className="flex items-center gap-2">
                        <Bot className="h-4 w-4 text-primary" />
                        {workflow.name}
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant={
                        workflow.status === "running" ? "default" :
                        workflow.status === "paused" ? "secondary" :
                        "destructive"
                      }>
                        {workflow.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="w-[200px]">
                      <div className="flex items-center gap-2">
                        <div className="w-full bg-secondary h-2 rounded-full overflow-hidden">
                          <div 
                            className={`h-full rounded-full ${
                              workflow.status === "running" ? "bg-primary" :
                              workflow.status === "paused" ? "bg-yellow-500" :
                              "bg-red-500"
                            }`} 
                            style={{ width: `${workflow.progress}%` }}
                          ></div>
                        </div>
                        <span className="text-sm text-muted-foreground">{workflow.progress}%</span>
                      </div>
                    </TableCell>
                    <TableCell>{workflow.currentStep}</TableCell>
                    <TableCell>{workflow.startTime}</TableCell>
                    <TableCell>{workflow.lastActivity}</TableCell>
                    <TableCell>{workflow.type}</TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        {workflow.toolsUsed.map((tool, index) => (
                          <Badge key={index} variant="secondary" className="text-xs">
                            {tool}
                          </Badge>
                        ))}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </TabsContent>

        <TabsContent value="completed">
          <div className="rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Agent Name</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Start Time</TableHead>
                  <TableHead>Duration</TableHead>
                  <TableHead>Outcome</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Tools</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {completedWorkflows.map((workflow) => (
                  <TableRow 
                    key={workflow.id}
                    className="cursor-pointer hover:bg-muted/50"
                    onClick={() => navigateToDetails(workflow.id)}
                  >
                    <TableCell className="font-medium">
                      <div className="flex items-center gap-2">
                        <Bot className="h-4 w-4 text-primary" />
                        {workflow.agentName}
                      </div>
                    </TableCell>
                    <TableCell>
                      {statusIcons[workflow.status]}
                    </TableCell>
                    <TableCell>{workflow.startTime}</TableCell>
                    <TableCell>{workflow.duration}</TableCell>
                    <TableCell>{workflow.outcome}</TableCell>
                    <TableCell>{workflow.type}</TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        {workflow.toolsUsed.map((tool, index) => (
                          <Badge key={index} variant="secondary" className="text-xs">
                            {tool}
                          </Badge>
                        ))}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </TabsContent>
      </Tabs>
    </>
    </ContentBlock>
  );
} 