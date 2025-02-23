"use client";

import React from "react";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Bot, Search, Filter, ArrowUpDown } from "lucide-react";

interface AgentCard {
  name: string;
  description: string;
  category: string;
  status: "available" | "running" | "stopped";
  lastUsed: string;
}

const agents: AgentCard[] = [
  {
    name: "Inventory Monitor",
    description: "Monitors inventory levels and alerts when stock falls below threshold",
    category: "E-commerce",
    status: "running",
    lastUsed: "Active now"
  },
  {
    name: "Customer Support Assistant",
    description: "Automatically tags and routes support tickets based on content",
    category: "Support",
    status: "available",
    lastUsed: "2 hours ago"
  },
  {
    name: "Marketing Analytics",
    description: "Generates daily reports from marketing data sources",
    category: "Analytics",
    status: "running",
    lastUsed: "Active now"
  },
  {
    name: "Document Scanner",
    description: "Scans documents for compliance violations and flags issues",
    category: "Compliance",
    status: "stopped",
    lastUsed: "1 day ago"
  }
];

const categories = ["All", "E-commerce", "Support", "Analytics", "Compliance", "Integration"];

export default function AgentsBrowsePage() {
  return (
    <div className="p-8">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-4xl font-bold">Browse Agents</h1>
          <p className="text-lg text-muted-foreground mt-2">
            Discover and deploy automation agents for your needs
          </p>
        </div>
        <button className="bg-primary text-primary-foreground hover:bg-primary/90 px-4 py-2 rounded-lg flex items-center gap-2">
          <Bot className="h-5 w-5" />
          Deploy New Agent
        </button>
      </div>

      <div className="flex gap-4 mb-6">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-muted-foreground h-4 w-4" />
          <Input
            placeholder="Search agents..."
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

      <div className="flex gap-4 mb-8 overflow-x-auto pb-2">
        {categories.map((category) => (
          <button
            key={category}
            className="px-4 py-2 rounded-full bg-secondary hover:bg-secondary/80 whitespace-nowrap"
          >
            {category}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {agents.map((agent, index) => (
          <Card key={index} className="p-6 hover:shadow-lg transition-shadow cursor-pointer">
            <div className="flex items-start justify-between mb-4">
              <div className="flex items-center gap-3">
                <div className="h-10 w-10 bg-primary/10 rounded-lg flex items-center justify-center">
                  <Bot className="h-6 w-6 text-primary" />
                </div>
                <div>
                  <h3 className="font-semibold">{agent.name}</h3>
                  <span className="text-sm text-muted-foreground">{agent.category}</span>
                </div>
              </div>
              <span className={`text-sm px-2 py-1 rounded-full ${
                agent.status === "running" ? "bg-green-100 text-green-700" :
                agent.status === "stopped" ? "bg-red-100 text-red-700" :
                "bg-secondary text-secondary-foreground"
              }`}>
                {agent.status}
              </span>
            </div>
            <p className="text-sm text-muted-foreground mb-4">{agent.description}</p>
            <div className="flex justify-between items-center text-sm">
              <span className="text-muted-foreground">Last used: {agent.lastUsed}</span>
              <button className="text-primary hover:underline">View Details</button>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
} 