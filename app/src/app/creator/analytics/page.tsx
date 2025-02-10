"use client";

import React from "react";
import { Card } from "@/components/ui/card";
import {
  Users,
  DollarSign,
  Star,
  BarChart2,
  TrendingUp,
  Clock,
  AlertTriangle,
  CheckCircle2,
  Calendar,
  Download,
  ChevronDown,
  ArrowUpRight,
  ArrowDownRight,
  Bot
} from "lucide-react";

interface PerformanceMetric {
  name: string;
  current: number;
  previous: number;
  trend: "up" | "down";
  unit: string;
}

interface TopAgent {
  name: string;
  category: string;
  metric: number;
  trend: "up" | "down";
}

const performanceMetrics: PerformanceMetric[] = [
  {
    name: "Total Revenue",
    current: 25670,
    previous: 21450,
    trend: "up",
    unit: "USD"
  },
  {
    name: "Active Users",
    current: 1850,
    previous: 1650,
    trend: "up",
    unit: "users"
  },
  {
    name: "Agent Runs",
    current: 58900,
    previous: 52300,
    trend: "up",
    unit: "runs"
  },
  {
    name: "Average Rating",
    current: 4.7,
    previous: 4.5,
    trend: "up",
    unit: "stars"
  }
];

const topAgentsByRevenue: TopAgent[] = [
  { name: "E-commerce Assistant", category: "Customer Service", metric: 12500, trend: "up" },
  { name: "Document Processor", category: "Document Processing", metric: 8900, trend: "up" },
  { name: "Analytics Reporter", category: "Analytics", metric: 4270, trend: "down" }
];

const topAgentsByRuns: TopAgent[] = [
  { name: "E-commerce Assistant", category: "Customer Service", metric: 25600, trend: "up" },
  { name: "Support Ticket Router", category: "Support", metric: 18900, trend: "up" },
  { name: "Data Sync Agent", category: "Integration", metric: 14400, trend: "down" }
];

const recentActivity = [
  {
    agent: "E-commerce Assistant",
    event: "New subscription",
    time: "5 minutes ago",
    type: "success"
  },
  {
    agent: "Document Processor",
    event: "Error reported",
    time: "15 minutes ago",
    type: "error"
  },
  {
    agent: "Analytics Reporter",
    event: "Version updated",
    time: "1 hour ago",
    type: "info"
  },
  {
    agent: "Support Ticket Router",
    event: "Performance alert",
    time: "2 hours ago",
    type: "warning"
  }
];

const MetricCard = ({ metric }: { metric: PerformanceMetric }) => {
  const percentChange = ((metric.current - metric.previous) / metric.previous * 100).toFixed(1);
  
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
      <div className="text-2xl font-bold mb-2">
        {metric.unit === "USD" ? "$" : ""}
        {metric.unit === "stars" ? metric.current.toFixed(1) : metric.current.toLocaleString()}
        {metric.unit === "stars" ? "★" : ""}
      </div>
      <div className={`text-sm ${metric.trend === "up" ? "text-green-600" : "text-red-600"}`}>
        {metric.trend === "up" ? "+" : "-"}{Math.abs(Number(percentChange))}% from last period
      </div>
    </Card>
  );
};

export default function AnalyticsPage() {
  return (
    <div className="p-8">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-4xl font-bold">Analytics</h1>
          <p className="text-lg text-muted-foreground mt-2">
            Monitor your agents' performance and insights
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
        {performanceMetrics.map((metric) => (
          <MetricCard key={metric.name} metric={metric} />
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
        <Card className="p-6">
          <h3 className="font-semibold mb-4">Top Agents by Revenue</h3>
          <div className="space-y-4">
            {topAgentsByRevenue.map((agent, index) => (
              <div key={index} className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="h-8 w-8 bg-primary/10 rounded-lg flex items-center justify-center">
                    <Bot className="h-4 w-4 text-primary" />
                  </div>
                  <div>
                    <div className="font-medium">{agent.name}</div>
                    <div className="text-sm text-muted-foreground">{agent.category}</div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <div className="text-right">
                    <div className="font-medium">${agent.metric.toLocaleString()}</div>
                    {agent.trend === "up" ? (
                      <div className="text-sm text-green-600">+12.5%</div>
                    ) : (
                      <div className="text-sm text-red-600">-8.3%</div>
                    )}
                  </div>
                  {agent.trend === "up" ? (
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
          <h3 className="font-semibold mb-4">Top Agents by Runs</h3>
          <div className="space-y-4">
            {topAgentsByRuns.map((agent, index) => (
              <div key={index} className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="h-8 w-8 bg-primary/10 rounded-lg flex items-center justify-center">
                    <Bot className="h-4 w-4 text-primary" />
                  </div>
                  <div>
                    <div className="font-medium">{agent.name}</div>
                    <div className="text-sm text-muted-foreground">{agent.category}</div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <div className="text-right">
                    <div className="font-medium">{agent.metric.toLocaleString()}</div>
                    {agent.trend === "up" ? (
                      <div className="text-sm text-green-600">+15.2%</div>
                    ) : (
                      <div className="text-sm text-red-600">-6.8%</div>
                    )}
                  </div>
                  {agent.trend === "up" ? (
                    <ArrowUpRight className="h-4 w-4 text-green-500" />
                  ) : (
                    <ArrowDownRight className="h-4 w-4 text-red-500" />
                  )}
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card className="col-span-2 p-6">
          <h3 className="font-semibold mb-4">Recent Activity</h3>
          <div className="space-y-4">
            {recentActivity.map((activity, index) => (
              <div key={index} className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className={`h-8 w-8 rounded-lg flex items-center justify-center ${
                    activity.type === "success" ? "bg-green-100" :
                    activity.type === "error" ? "bg-red-100" :
                    activity.type === "warning" ? "bg-yellow-100" :
                    "bg-blue-100"
                  }`}>
                    {activity.type === "success" ? (
                      <CheckCircle2 className="h-4 w-4 text-green-600" />
                    ) : activity.type === "error" ? (
                      <AlertTriangle className="h-4 w-4 text-red-600" />
                    ) : activity.type === "warning" ? (
                      <AlertTriangle className="h-4 w-4 text-yellow-600" />
                    ) : (
                      <TrendingUp className="h-4 w-4 text-blue-600" />
                    )}
                  </div>
                  <div>
                    <div className="font-medium">{activity.agent}</div>
                    <div className="text-sm text-muted-foreground">{activity.event}</div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Clock className="h-4 w-4 text-muted-foreground" />
                  <span className="text-sm text-muted-foreground">{activity.time}</span>
                </div>
              </div>
            ))}
          </div>
        </Card>

        <Card className="p-6">
          <h3 className="font-semibold mb-4">Quick Stats</h3>
          <div className="space-y-4">
            <div className="flex justify-between items-center">
              <span className="text-sm text-muted-foreground">Active Agents</span>
              <span className="font-medium">8</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-sm text-muted-foreground">Total Subscriptions</span>
              <span className="font-medium">245</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-sm text-muted-foreground">Average Response Time</span>
              <span className="font-medium">1.2s</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-sm text-muted-foreground">Error Rate</span>
              <span className="font-medium">0.8%</span>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
} 