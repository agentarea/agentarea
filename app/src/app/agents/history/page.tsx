"use client";

import React from "react";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Search,
  Filter,
  ArrowUpDown,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Clock,
  Calendar,
  Download
} from "lucide-react";

interface AgentRun {
  id: string;
  agentName: string;
  status: "success" | "failed" | "warning";
  startTime: string;
  duration: string;
  outcome: string;
  type: string;
  resources: string;
}

const agentRuns: AgentRun[] = [
  {
    id: "run-1",
    agentName: "Inventory Monitor",
    status: "success",
    startTime: "2024-02-10 14:30:00",
    duration: "5m 30s",
    outcome: "Stock levels checked, no alerts needed",
    type: "Scheduled",
    resources: "3 data sources processed"
  },
  {
    id: "run-2",
    agentName: "Support Ticket Router",
    status: "warning",
    startTime: "2024-02-10 14:15:00",
    duration: "2m 45s",
    outcome: "Processed 15 tickets, 2 required manual review",
    type: "Event Triggered",
    resources: "15 tickets processed"
  },
  {
    id: "run-3",
    agentName: "Analytics Reporter",
    status: "failed",
    startTime: "2024-02-10 14:00:00",
    duration: "1m 15s",
    outcome: "Failed to connect to data source",
    type: "Manual",
    resources: "Connection error"
  },
  {
    id: "run-4",
    agentName: "Data Sync Agent",
    status: "success",
    startTime: "2024-02-10 13:45:00",
    duration: "8m 20s",
    outcome: "Successfully synced 1,234 records",
    type: "Scheduled",
    resources: "1,234 records processed"
  }
];

const statusIcons = {
  success: <CheckCircle2 className="h-5 w-5 text-green-500" />,
  warning: <AlertTriangle className="h-5 w-5 text-yellow-500" />,
  failed: <XCircle className="h-5 w-5 text-red-500" />
};

export default function AgentHistoryPage() {
  return (
    <div className="p-8">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-4xl font-bold">Agent History</h1>
          <p className="text-lg text-muted-foreground mt-2">
            View past agent runs and their outcomes
          </p>
        </div>
        <div className="flex gap-4">
          <button className="px-4 py-2 border rounded-lg flex items-center gap-2 hover:bg-secondary">
            <Calendar className="h-4 w-4" />
            Date Range
          </button>
          <button className="px-4 py-2 border rounded-lg flex items-center gap-2 hover:bg-secondary">
            <Download className="h-4 w-4" />
            Export
          </button>
        </div>
      </div>

      <div className="flex gap-4 mb-6">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-muted-foreground h-4 w-4" />
          <Input
            placeholder="Search agent runs..."
            className="pl-10"
          />
        </div>
        <button className="px-4 py-2 border rounded-lg flex items-center gap-2 hover:bg-secondary">
          <Filter className="h-4 w-4" />
          Filter
        </button>
        <button className="px-4 py-2 border rounded-lg flex items-center gap-2 hover:bg-secondary">
          <ArrowUpDown className="h-4 w-4" />
          Sort
        </button>
      </div>

      <Card className="overflow-hidden">
        <div className="grid grid-cols-[auto_1fr_auto_auto_1fr_auto] gap-6 p-4 bg-muted text-sm font-medium">
          <div>Status</div>
          <div>Agent</div>
          <div>Type</div>
          <div>Duration</div>
          <div>Outcome</div>
          <div>Resources</div>
        </div>
        <div className="divide-y">
          {agentRuns.map((run) => (
            <div
              key={run.id}
              className="grid grid-cols-[auto_1fr_auto_auto_1fr_auto] gap-6 p-4 items-center hover:bg-muted/50 cursor-pointer"
            >
              <div className="flex items-center gap-2">
                {statusIcons[run.status]}
                <span className={`text-sm ${
                  run.status === "success" ? "text-green-700" :
                  run.status === "warning" ? "text-yellow-700" :
                  "text-red-700"
                }`}>
                  {run.status.charAt(0).toUpperCase() + run.status.slice(1)}
                </span>
              </div>
              <div>
                <div className="font-medium">{run.agentName}</div>
                <div className="text-sm text-muted-foreground flex items-center gap-1">
                  <Clock className="h-3 w-3" />
                  {run.startTime}
                </div>
              </div>
              <div className="text-sm text-muted-foreground">{run.type}</div>
              <div className="text-sm text-muted-foreground">{run.duration}</div>
              <div className="text-sm text-muted-foreground">{run.outcome}</div>
              <div className="text-sm text-muted-foreground">{run.resources}</div>
            </div>
          ))}
        </div>
      </Card>

      <div className="mt-4 flex justify-between items-center text-sm text-muted-foreground">
        <div>Showing 4 of 156 runs</div>
        <div className="flex gap-2">
          <button className="px-3 py-1 rounded hover:bg-secondary">Previous</button>
          <button className="px-3 py-1 bg-primary text-primary-foreground rounded">1</button>
          <button className="px-3 py-1 rounded hover:bg-secondary">2</button>
          <button className="px-3 py-1 rounded hover:bg-secondary">3</button>
          <button className="px-3 py-1 rounded hover:bg-secondary">Next</button>
        </div>
      </div>
    </div>
  );
} 