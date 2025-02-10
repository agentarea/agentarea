"use client";

import React from "react";
import { Card } from "@/components/ui/card";
import { Bot, Play, Pause, RefreshCw, XCircle, MoreVertical, Activity } from "lucide-react";

interface RunningAgent {
  id: string;
  name: string;
  description: string;
  status: "running" | "paused" | "error";
  uptime: string;
  resourceUsage: {
    cpu: string;
    memory: string;
  };
  lastActivity: string;
  type: string;
}

const runningAgents: RunningAgent[] = [
  {
    id: "agent-1",
    name: "Inventory Monitor",
    description: "Monitoring stock levels across all warehouses",
    status: "running",
    uptime: "2d 5h 30m",
    resourceUsage: {
      cpu: "2%",
      memory: "256MB"
    },
    lastActivity: "2 minutes ago",
    type: "E-commerce"
  },
  {
    id: "agent-2",
    name: "Support Ticket Router",
    description: "Processing and routing customer support tickets",
    status: "running",
    uptime: "5d 12h 45m",
    resourceUsage: {
      cpu: "5%",
      memory: "512MB"
    },
    lastActivity: "30 seconds ago",
    type: "Support"
  },
  {
    id: "agent-3",
    name: "Analytics Reporter",
    description: "Generating daily analytics reports",
    status: "paused",
    uptime: "15h 20m",
    resourceUsage: {
      cpu: "0%",
      memory: "128MB"
    },
    lastActivity: "1 hour ago",
    type: "Analytics"
  },
  {
    id: "agent-4",
    name: "Data Sync Agent",
    description: "Synchronizing data between systems",
    status: "error",
    uptime: "0h 5m",
    resourceUsage: {
      cpu: "15%",
      memory: "1GB"
    },
    lastActivity: "5 minutes ago",
    type: "Integration"
  }
];

export default function RunningAgentsPage() {
  return (
    <div className="p-8">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-4xl font-bold">Running Agents</h1>
          <p className="text-lg text-muted-foreground mt-2">
            Monitor and manage your active automation agents
          </p>
        </div>
        <div className="flex gap-4">
          <button className="px-4 py-2 border rounded-lg flex items-center gap-2 hover:bg-secondary">
            <RefreshCw className="h-4 w-4" />
            Refresh
          </button>
          <button className="bg-primary text-primary-foreground hover:bg-primary/90 px-4 py-2 rounded-lg flex items-center gap-2">
            <Bot className="h-5 w-5" />
            Deploy New Agent
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6">
        {runningAgents.map((agent) => (
          <Card key={agent.id} className="p-6">
            <div className="flex items-start justify-between">
              <div className="flex items-start gap-4">
                <div className="h-12 w-12 bg-primary/10 rounded-lg flex items-center justify-center">
                  <Bot className="h-7 w-7 text-primary" />
                </div>
                <div>
                  <div className="flex items-center gap-3">
                    <h3 className="font-semibold text-lg">{agent.name}</h3>
                    <span className={`text-sm px-2 py-1 rounded-full ${
                      agent.status === "running" ? "bg-green-100 text-green-700" :
                      agent.status === "paused" ? "bg-yellow-100 text-yellow-700" :
                      "bg-red-100 text-red-700"
                    }`}>
                      {agent.status}
                    </span>
                  </div>
                  <p className="text-sm text-muted-foreground mt-1">{agent.description}</p>
                  <div className="flex gap-6 mt-4">
                    <div>
                      <p className="text-sm font-medium">Uptime</p>
                      <p className="text-sm text-muted-foreground">{agent.uptime}</p>
                    </div>
                    <div>
                      <p className="text-sm font-medium">CPU Usage</p>
                      <p className="text-sm text-muted-foreground">{agent.resourceUsage.cpu}</p>
                    </div>
                    <div>
                      <p className="text-sm font-medium">Memory Usage</p>
                      <p className="text-sm text-muted-foreground">{agent.resourceUsage.memory}</p>
                    </div>
                    <div>
                      <p className="text-sm font-medium">Last Activity</p>
                      <p className="text-sm text-muted-foreground">{agent.lastActivity}</p>
                    </div>
                    <div>
                      <p className="text-sm font-medium">Type</p>
                      <p className="text-sm text-muted-foreground">{agent.type}</p>
                    </div>
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2">
                {agent.status === "running" ? (
                  <button className="p-2 hover:bg-secondary rounded-lg" title="Pause">
                    <Pause className="h-5 w-5" />
                  </button>
                ) : agent.status === "paused" ? (
                  <button className="p-2 hover:bg-secondary rounded-lg" title="Resume">
                    <Play className="h-5 w-5" />
                  </button>
                ) : null}
                <button className="p-2 hover:bg-secondary rounded-lg" title="Stop">
                  <XCircle className="h-5 w-5" />
                </button>
                <button className="p-2 hover:bg-secondary rounded-lg" title="View Logs">
                  <Activity className="h-5 w-5" />
                </button>
                <button className="p-2 hover:bg-secondary rounded-lg" title="More Options">
                  <MoreVertical className="h-5 w-5" />
                </button>
              </div>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
} 