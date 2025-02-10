"use client";

import React from "react";
import { Card } from "@/components/ui/card";
import {
  Bot,
  Database,
  Users,
  Clock,
  Calendar,
  Download,
  ChevronDown,
  BarChart2,
  ArrowUpRight,
  ArrowDownRight,
  AlertTriangle
} from "lucide-react";

interface UsageMetric {
  name: string;
  current: number;
  limit: number;
  unit: string;
  trend: "up" | "down";
  change: number;
}

const usageMetrics: UsageMetric[] = [
  {
    name: "Active Agents",
    current: 15,
    limit: 25,
    unit: "agents",
    trend: "up",
    change: 20
  },
  {
    name: "Agent Runs",
    current: 45670,
    limit: 100000,
    unit: "runs",
    trend: "up",
    change: 15
  },
  {
    name: "Data Storage",
    current: 256,
    limit: 500,
    unit: "GB",
    trend: "up",
    change: 10
  },
  {
    name: "API Calls",
    current: 890000,
    limit: 1000000,
    unit: "calls",
    trend: "down",
    change: 5
  }
];

const topConsumers = [
  {
    name: "E-commerce Assistant",
    type: "Agent",
    usage: "25% of total runs",
    trend: "up"
  },
  {
    name: "Analytics Pipeline",
    type: "Workflow",
    usage: "15% of storage",
    trend: "up"
  },
  {
    name: "Customer Support Team",
    type: "Team",
    usage: "30% of API calls",
    trend: "down"
  }
];

const alerts = [
  {
    title: "API Usage Warning",
    description: "Approaching monthly API call limit (89%)",
    type: "warning"
  },
  {
    title: "Storage Growth",
    description: "Storage usage increased by 25% this month",
    type: "info"
  }
];

const UsageCard = ({ metric }: { metric: UsageMetric }) => {
  const percentage = (metric.current / metric.limit) * 100;
  const statusColor = 
    percentage > 90 ? "text-red-500" :
    percentage > 75 ? "text-yellow-500" :
    "text-green-500";

  return (
    <Card className="p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-medium text-sm">{metric.name}</h3>
        {metric.trend === "up" ? (
          <ArrowUpRight className="h-4 w-4 text-green-500" />
        ) : (
          <ArrowDownRight className="h-4 w-4 text-red-500" />
        )}
      </div>
      <div className="mb-4">
        <div className="flex justify-between mb-2">
          <span className="text-2xl font-bold">{metric.current.toLocaleString()}</span>
          <span className="text-sm text-muted-foreground">of {metric.limit.toLocaleString()} {metric.unit}</span>
        </div>
        <div className="h-2 bg-secondary rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full ${statusColor} bg-current`}
            style={{ width: `${percentage}%` }}
          />
        </div>
      </div>
      <div className={`text-sm ${metric.trend === "up" ? "text-green-600" : "text-red-600"}`}>
        {metric.trend === "up" ? "+" : "-"}{metric.change}% from last period
      </div>
    </Card>
  );
};

export default function UsagePage() {
  return (
    <div className="p-8">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-4xl font-bold">Usage & Limits</h1>
          <p className="text-lg text-muted-foreground mt-2">
            Monitor your organization's resource usage and limits
          </p>
        </div>
        <div className="flex gap-4">
          <button className="px-4 py-2 border rounded-lg flex items-center gap-2 hover:bg-secondary">
            <Calendar className="h-4 w-4" />
            Last 30 Days
            <ChevronDown className="h-4 w-4" />
          </button>
          <button className="px-4 py-2 border rounded-lg flex items-center gap-2 hover:bg-secondary">
            <Download className="h-4 w-4" />
            Export
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
        {usageMetrics.map((metric) => (
          <UsageCard key={metric.name} metric={metric} />
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card className="col-span-2 p-6">
          <h3 className="font-semibold mb-4">Top Resource Consumers</h3>
          <div className="space-y-4">
            {topConsumers.map((consumer, index) => (
              <div key={index} className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="h-10 w-10 bg-primary/10 rounded-lg flex items-center justify-center">
                    {consumer.type === "Agent" ? (
                      <Bot className="h-5 w-5 text-primary" />
                    ) : consumer.type === "Team" ? (
                      <Users className="h-5 w-5 text-primary" />
                    ) : (
                      <Database className="h-5 w-5 text-primary" />
                    )}
                  </div>
                  <div>
                    <div className="font-medium">{consumer.name}</div>
                    <div className="text-sm text-muted-foreground">{consumer.type}</div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <div className="text-right">
                    <div className="font-medium">{consumer.usage}</div>
                    {consumer.trend === "up" ? (
                      <div className="text-sm text-green-600">+12.5%</div>
                    ) : (
                      <div className="text-sm text-red-600">-8.3%</div>
                    )}
                  </div>
                  {consumer.trend === "up" ? (
                    <ArrowUpRight className="h-4 w-4 text-green-500" />
                  ) : (
                    <ArrowDownRight className="h-4 w-4 text-red-500" />
                  )}
                </div>
              </div>
            ))}
          </div>
        </Card>

        <Card className="p-6">
          <h3 className="font-semibold mb-4">Usage Alerts</h3>
          <div className="space-y-4">
            {alerts.map((alert, index) => (
              <div key={index} className="flex items-start gap-3">
                <div className={`h-8 w-8 rounded-lg flex items-center justify-center ${
                  alert.type === "warning" ? "bg-yellow-100" : "bg-blue-100"
                }`}>
                  {alert.type === "warning" ? (
                    <AlertTriangle className="h-4 w-4 text-yellow-600" />
                  ) : (
                    <BarChart2 className="h-4 w-4 text-blue-600" />
                  )}
                </div>
                <div>
                  <div className="font-medium">{alert.title}</div>
                  <div className="text-sm text-muted-foreground">{alert.description}</div>
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
} 