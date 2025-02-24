"use client";

import React from "react";
import { Card } from "@/components/ui/card";
import { Bot, Database, Code2, Activity, MessageSquare } from "lucide-react";
import Link from "next/link";

interface StatCardProps {
  title: string;
  value: string;
  icon: React.ReactNode;
  description: string;
}

const StatCard = ({ title, value, icon, description }: StatCardProps) => (
  <Card className="p-6">
    <div className="flex items-center justify-between">
      <div>
        <p className="text-sm font-medium text-muted-foreground">{title}</p>
        <h3 className="text-2xl font-bold mt-2">{value}</h3>
      </div>
      <div className="h-12 w-12 bg-primary/10 rounded-full flex items-center justify-center">
        {icon}
      </div>
    </div>
    <p className="text-sm text-muted-foreground mt-2">{description}</p>
  </Card>
);

export default function HomePage() {
  return (
    <div className="p-8">
      <div className="mb-8">
        <h1 className="text-4xl font-bold">Welcome to AgentMesh</h1>
        <p className="text-lg text-muted-foreground mt-2">
          Your central hub for deploying, managing, and orchestrating automation agents
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
        <StatCard
          title="Active Agents"
          value="12"
          icon={<Bot className="h-6 w-6 text-primary" />}
          description="Currently running automation agents"
        />
        <StatCard
          title="Data Sources"
          value="8"
          icon={<Database className="h-6 w-6 text-primary" />}
          description="Connected data sources and integrations"
        />
        <StatCard
          title="Workflows"
          value="5"
          icon={<Code2 className="h-6 w-6 text-primary" />}
          description="Active automation workflows"
        />
        <StatCard
          title="Tasks Today"
          value="156"
          icon={<Activity className="h-6 w-6 text-primary" />}
          description="Tasks completed in the last 24 hours"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card className="p-6">
          <h2 className="text-xl font-semibold mb-4">Quick Actions</h2>
          <div className="space-y-4">
            <button className="w-full text-left px-4 py-3 rounded-lg hover:bg-secondary transition-colors">
              <span className="font-medium">Deploy New Agent</span>
              <p className="text-sm text-muted-foreground">Create and deploy a new automation agent</p>
            </button>
            <button className="w-full text-left px-4 py-3 rounded-lg hover:bg-secondary transition-colors">
              <span className="font-medium">Connect Data Source</span>
              <p className="text-sm text-muted-foreground">Add a new data source or integration</p>
            </button>
            <button className="w-full text-left px-4 py-3 rounded-lg hover:bg-secondary transition-colors">
              <span className="font-medium">Create Workflow</span>
              <p className="text-sm text-muted-foreground">Build a new automation workflow</p>
            </button>
            <Link href="/home/chat" className="block">
              <div className="w-full text-left px-4 py-3 rounded-lg hover:bg-secondary transition-colors">
                <div className="flex items-center">
                  <MessageSquare className="h-5 w-5 text-primary mr-2" />
                  <span className="font-medium">Open Agent Chat</span>
                </div>
                <p className="text-sm text-muted-foreground">Interact with agents through our advanced chat interface</p>
              </div>
            </Link>
          </div>
        </Card>

        <Card className="p-6">
          <h2 className="text-xl font-semibold mb-4">Recent Activity</h2>
          <div className="space-y-4">
            {[
              {
                title: "Inventory Monitor Agent",
                description: "Alert: Low stock detected for SKU-123",
                time: "10 minutes ago"
              },
              {
                title: "Customer Support Agent",
                description: "Processed 25 support tickets",
                time: "1 hour ago"
              },
              {
                title: "Analytics Workflow",
                description: "Generated daily marketing report",
                time: "2 hours ago"
              }
            ].map((activity, index) => (
              <div key={index} className="flex items-start space-x-4 p-3 rounded-lg hover:bg-secondary transition-colors">
                <div className="flex-1">
                  <p className="font-medium">{activity.title}</p>
                  <p className="text-sm text-muted-foreground">{activity.description}</p>
                </div>
                <span className="text-xs text-muted-foreground">{activity.time}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
} 