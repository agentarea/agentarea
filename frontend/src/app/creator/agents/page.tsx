"use client";

import React from "react";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Bot,
  Search,
  Filter,
  ArrowUpDown,
  BarChart2,
  Users,
  Star,
  Plus,
  MoreVertical,
  Edit,
  Copy,
  Trash2,
  ExternalLink
} from "lucide-react";

interface CreatedAgent {
  id: string;
  name: string;
  description: string;
  status: "published" | "draft" | "archived";
  version: string;
  stats: {
    users: number;
    runs: number;
    rating: number;
  };
  lastUpdated: string;
  category: string;
}

const createdAgents: CreatedAgent[] = [
  {
    id: "agent-1",
    name: "E-commerce Assistant",
    description: "AI-powered assistant for handling customer inquiries and product recommendations",
    status: "published",
    version: "2.1.0",
    stats: {
      users: 1234,
      runs: 45678,
      rating: 4.8
    },
    lastUpdated: "2 days ago",
    category: "Customer Service"
  },
  {
    id: "agent-2",
    name: "Data Analyzer",
    description: "Automated data analysis and report generation agent",
    status: "draft",
    version: "1.0.0",
    stats: {
      users: 0,
      runs: 0,
      rating: 0
    },
    lastUpdated: "1 hour ago",
    category: "Analytics"
  },
  {
    id: "agent-3",
    name: "Document Processor",
    description: "Process and extract information from various document formats",
    status: "published",
    version: "1.5.0",
    stats: {
      users: 567,
      runs: 12345,
      rating: 4.5
    },
    lastUpdated: "5 days ago",
    category: "Document Processing"
  },
  {
    id: "agent-4",
    name: "Legacy Support Bot",
    description: "Support agent for legacy system maintenance",
    status: "archived",
    version: "1.0.0",
    stats: {
      users: 123,
      runs: 5678,
      rating: 4.2
    },
    lastUpdated: "3 months ago",
    category: "Support"
  }
];

const statusColors = {
  published: "bg-green-100 text-green-700",
  draft: "bg-yellow-100 text-yellow-700",
  archived: "bg-neutral-100 text-neutral-700"
};

export default function CreatorAgentsPage() {
  return (
    <div className="p-8">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-4xl font-bold">My Agents</h1>
          <p className="text-lg text-muted-foreground mt-2">
            Manage and monitor your created agents
          </p>
        </div>
        <button className="bg-primary text-primary-foreground hover:bg-primary/90 px-4 py-2 rounded-lg flex items-center gap-2">
          <Plus className="h-5 w-5" />
          Create New Agent
        </button>
      </div>

      <div className="flex gap-4 mb-6">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-muted-foreground h-4 w-4" />
          <Input
            placeholder="Search your agents..."
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

      <div className="grid grid-cols-1 gap-6">
        {createdAgents.map((agent) => (
          <Card key={agent.id} className="p-6">
            <div className="flex items-start justify-between">
              <div className="flex items-start gap-4">
                <div className="h-12 w-12 bg-primary/10 rounded-lg flex items-center justify-center">
                  <Bot className="h-6 w-6 text-primary" />
                </div>
                <div>
                  <div className="flex items-center gap-3">
                    <h3 className="font-semibold text-lg">{agent.name}</h3>
                    <span className={`text-sm px-2 py-1 rounded-full ${statusColors[agent.status]}`}>
                      {agent.status.charAt(0).toUpperCase() + agent.status.slice(1)}
                    </span>
                  </div>
                  <p className="text-sm text-muted-foreground mt-1">{agent.description}</p>
                  <div className="flex gap-6 mt-4">
                    <div className="flex items-center gap-2">
                      <Users className="h-4 w-4 text-muted-foreground" />
                      <span className="text-sm text-muted-foreground">{agent.stats.users} users</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <BarChart2 className="h-4 w-4 text-muted-foreground" />
                      <span className="text-sm text-muted-foreground">{agent.stats.runs} runs</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <Star className="h-4 w-4 text-muted-foreground" />
                      <span className="text-sm text-muted-foreground">{agent.stats.rating} rating</span>
                    </div>
                    <div className="text-sm text-muted-foreground">
                      Version {agent.version}
                    </div>
                    <div className="text-sm text-muted-foreground">
                      Updated {agent.lastUpdated}
                    </div>
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2">
                {agent.status === "published" && (
                  <button className="p-2 hover:bg-secondary rounded-lg" title="View in Marketplace">
                    <ExternalLink className="h-5 w-5" />
                  </button>
                )}
                <button className="p-2 hover:bg-secondary rounded-lg" title="Edit">
                  <Edit className="h-5 w-5" />
                </button>
                <button className="p-2 hover:bg-secondary rounded-lg" title="Duplicate">
                  <Copy className="h-5 w-5" />
                </button>
                <button className="p-2 hover:bg-secondary rounded-lg" title="Delete">
                  <Trash2 className="h-5 w-5" />
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