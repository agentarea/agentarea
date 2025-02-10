"use client";

import React from "react";
import { Card } from "@/components/ui/card";
import {
  Bot,
  TrendingUp,
  Users,
  DollarSign,
  Star,
  BarChart2,
  ArrowUpRight,
  ArrowDownRight,
  ChevronRight,
  Settings
} from "lucide-react";

interface PublishedAgent {
  id: string;
  name: string;
  description: string;
  price: number;
  stats: {
    users: number;
    revenue: number;
    rating: number;
    runs: number;
  };
  trends: {
    users: "up" | "down";
    revenue: "up" | "down";
    rating: "up" | "down";
    runs: "up" | "down";
  };
  lastUpdated: string;
  category: string;
}

const publishedAgents: PublishedAgent[] = [
  {
    id: "agent-1",
    name: "E-commerce Assistant",
    description: "AI-powered assistant for handling customer inquiries and product recommendations",
    price: 49.99,
    stats: {
      users: 1234,
      revenue: 15780,
      rating: 4.8,
      runs: 45678
    },
    trends: {
      users: "up",
      revenue: "up",
      rating: "up",
      runs: "up"
    },
    lastUpdated: "2 days ago",
    category: "Customer Service"
  },
  {
    id: "agent-2",
    name: "Document Processor",
    description: "Process and extract information from various document formats",
    price: 29.99,
    stats: {
      users: 567,
      revenue: 4890,
      rating: 4.5,
      runs: 12345
    },
    trends: {
      users: "up",
      revenue: "down",
      rating: "up",
      runs: "down"
    },
    lastUpdated: "5 days ago",
    category: "Document Processing"
  }
];

const StatCard = ({ title, value, trend, icon }: { title: string; value: string; trend: "up" | "down"; icon: React.ReactNode }) => (
  <Card className="p-6">
    <div className="flex items-center justify-between mb-4">
      <div className="flex items-center gap-2">
        {icon}
        <h3 className="font-medium text-sm">{title}</h3>
      </div>
      {trend === "up" ? (
        <ArrowUpRight className="h-4 w-4 text-green-500" />
      ) : (
        <ArrowDownRight className="h-4 w-4 text-red-500" />
      )}
    </div>
    <p className="text-2xl font-bold">{value}</p>
  </Card>
);

export default function PublicationsPage() {
  const totalStats = {
    users: publishedAgents.reduce((sum, agent) => sum + agent.stats.users, 0),
    revenue: publishedAgents.reduce((sum, agent) => sum + agent.stats.revenue, 0),
    rating: publishedAgents.reduce((sum, agent) => sum + agent.stats.rating, 0) / publishedAgents.length,
    runs: publishedAgents.reduce((sum, agent) => sum + agent.stats.runs, 0)
  };

  return (
    <div className="p-8">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-4xl font-bold">Publications</h1>
          <p className="text-lg text-muted-foreground mt-2">
            Monitor your published agents' performance
          </p>
        </div>
        <button className="px-4 py-2 border rounded-lg flex items-center gap-2 hover:bg-secondary">
          <Settings className="h-4 w-4" />
          Marketplace Settings
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
        <StatCard
          title="Total Users"
          value={totalStats.users.toLocaleString()}
          trend="up"
          icon={<Users className="h-4 w-4 text-blue-500" />}
        />
        <StatCard
          title="Total Revenue"
          value={`$${totalStats.revenue.toLocaleString()}`}
          trend="up"
          icon={<DollarSign className="h-4 w-4 text-green-500" />}
        />
        <StatCard
          title="Average Rating"
          value={totalStats.rating.toFixed(1)}
          trend="up"
          icon={<Star className="h-4 w-4 text-yellow-500" />}
        />
        <StatCard
          title="Total Runs"
          value={totalStats.runs.toLocaleString()}
          trend="up"
          icon={<BarChart2 className="h-4 w-4 text-purple-500" />}
        />
      </div>

      <div className="space-y-6">
        {publishedAgents.map((agent) => (
          <Card key={agent.id} className="p-6">
            <div className="flex items-start justify-between">
              <div className="flex items-start gap-4">
                <div className="h-12 w-12 bg-primary/10 rounded-lg flex items-center justify-center">
                  <Bot className="h-6 w-6 text-primary" />
                </div>
                <div>
                  <div className="flex items-center gap-3">
                    <h3 className="font-semibold text-lg">{agent.name}</h3>
                    <span className="text-sm px-2 py-1 rounded-full bg-green-100 text-green-700">
                      Published
                    </span>
                  </div>
                  <p className="text-sm text-muted-foreground mt-1">{agent.description}</p>
                  <div className="flex gap-6 mt-4">
                    <div className="flex items-center gap-2">
                      <Users className="h-4 w-4 text-muted-foreground" />
                      <span className="text-sm text-muted-foreground">
                        {agent.stats.users.toLocaleString()} users
                        {agent.trends.users === "up" ? (
                          <ArrowUpRight className="h-3 w-3 text-green-500 inline ml-1" />
                        ) : (
                          <ArrowDownRight className="h-3 w-3 text-red-500 inline ml-1" />
                        )}
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      <DollarSign className="h-4 w-4 text-muted-foreground" />
                      <span className="text-sm text-muted-foreground">
                        ${agent.stats.revenue.toLocaleString()}
                        {agent.trends.revenue === "up" ? (
                          <ArrowUpRight className="h-3 w-3 text-green-500 inline ml-1" />
                        ) : (
                          <ArrowDownRight className="h-3 w-3 text-red-500 inline ml-1" />
                        )}
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      <Star className="h-4 w-4 text-muted-foreground" />
                      <span className="text-sm text-muted-foreground">
                        {agent.stats.rating} rating
                        {agent.trends.rating === "up" ? (
                          <ArrowUpRight className="h-3 w-3 text-green-500 inline ml-1" />
                        ) : (
                          <ArrowDownRight className="h-3 w-3 text-red-500 inline ml-1" />
                        )}
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      <BarChart2 className="h-4 w-4 text-muted-foreground" />
                      <span className="text-sm text-muted-foreground">
                        {agent.stats.runs.toLocaleString()} runs
                        {agent.trends.runs === "up" ? (
                          <ArrowUpRight className="h-3 w-3 text-green-500 inline ml-1" />
                        ) : (
                          <ArrowDownRight className="h-3 w-3 text-red-500 inline ml-1" />
                        )}
                      </span>
                    </div>
                    <div className="text-sm text-muted-foreground">
                      Updated {agent.lastUpdated}
                    </div>
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-4">
                <div className="text-right">
                  <div className="text-2xl font-bold">${agent.price}</div>
                  <div className="text-sm text-muted-foreground">per month</div>
                </div>
                <button className="p-2 hover:bg-secondary rounded-lg">
                  <ChevronRight className="h-5 w-5" />
                </button>
              </div>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
} 