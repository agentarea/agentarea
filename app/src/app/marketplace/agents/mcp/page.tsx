"use client";

import React, { useState } from "react";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Bot,
  Search,
  Filter,
  ArrowUpDown,
  Star,
  Users,
  BarChart2,
  ChevronRight,
  Shield,
  Check,
  Info
} from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Badge } from "@/components/ui/badge";

interface MCPAgent {
  id: string;
  name: string;
  description: string;
  creator: string;
  price: number;
  stats: {
    rating: number;
    users: number;
    runs: number;
  };
  mcpFeatures: {
    messageRouting: boolean;
    toolUse: boolean;
    multiAgentCollaboration: boolean;
    humanInTheLoop: boolean;
  };
  category: string;
}

const mcpAgents: MCPAgent[] = [
  {
    id: "mcp-agent-1",
    name: "MCP Router Pro",
    description: "Advanced message routing agent with full MCP protocol support",
    creator: "AgentMesh",
    price: 79.99,
    stats: {
      rating: 4.9,
      users: 1567,
      runs: 78945
    },
    mcpFeatures: {
      messageRouting: true,
      toolUse: true,
      multiAgentCollaboration: true,
      humanInTheLoop: true
    },
    category: "Routing"
  },
  {
    id: "mcp-agent-2",
    name: "Tool Specialist",
    description: "Specialized agent for tool use and integration with MCP protocol",
    creator: "ToolWorks Inc",
    price: 49.99,
    stats: {
      rating: 4.7,
      users: 890,
      runs: 34567
    },
    mcpFeatures: {
      messageRouting: false,
      toolUse: true,
      multiAgentCollaboration: true,
      humanInTheLoop: false
    },
    category: "Tool Integration"
  },
  {
    id: "mcp-agent-3",
    name: "Collaboration Hub",
    description: "Multi-agent collaboration coordinator with MCP support",
    creator: "CollabTech",
    price: 89.99,
    stats: {
      rating: 4.8,
      users: 1234,
      runs: 56789
    },
    mcpFeatures: {
      messageRouting: true,
      toolUse: true,
      multiAgentCollaboration: true,
      humanInTheLoop: true
    },
    category: "Collaboration"
  }
];

const categories = ["All", "Routing", "Tool Integration", "Collaboration", "Human-in-the-Loop"];

export default function MCPAgentsPage() {
  const [selectedCategory, setSelectedCategory] = useState("All");

  return (
    <div className="p-8">
      <div className="flex justify-between items-center mb-8">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-4xl font-bold">MCP Compatible Agents</h1>
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger>
                  <Info className="h-5 w-5 text-muted-foreground" />
                </TooltipTrigger>
                <TooltipContent className="max-w-md">
                  <p>MCP (Message Control Protocol) compatible agents support standardized message routing, tool use, multi-agent collaboration, and human-in-the-loop interactions.</p>
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>
          <p className="text-lg text-muted-foreground mt-2">
            Discover agents that support the Message Control Protocol (MCP) standard
          </p>
        </div>
        <Button variant="default">Create MCP Agent</Button>
      </div>

      <div className="flex gap-4 mb-6">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-muted-foreground h-4 w-4" />
          <Input
            placeholder="Search MCP agents..."
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
            className={`px-4 py-2 rounded-full ${selectedCategory === category ? 'bg-primary text-primary-foreground' : 'bg-secondary hover:bg-secondary/80'} whitespace-nowrap`}
            onClick={() => setSelectedCategory(category)}
          >
            {category}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {mcpAgents
          .filter(agent => selectedCategory === "All" || agent.category === selectedCategory)
          .map((agent) => (
          <Card key={agent.id} className="p-6 hover:shadow-lg transition-shadow cursor-pointer">
            <div className="flex items-start justify-between mb-4">
              <div className="flex items-center gap-3">
                <div className="h-12 w-12 bg-primary/10 rounded-lg flex items-center justify-center">
                  <Bot className="h-6 w-6 text-primary" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="font-semibold">{agent.name}</h3>
                    <Badge variant="outline" className="bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300">MCP</Badge>
                  </div>
                  <span className="text-sm text-muted-foreground">by {agent.creator}</span>
                </div>
              </div>
            </div>
            <p className="text-sm text-muted-foreground mb-4">{agent.description}</p>
            
            <div className="grid grid-cols-2 gap-2 mb-4">
              <div className="flex items-center gap-2 text-sm">
                <div className={agent.mcpFeatures.messageRouting ? "text-green-500" : "text-muted-foreground"}>
                  {agent.mcpFeatures.messageRouting ? <Check className="h-4 w-4" /> : <span className="h-4 w-4 inline-block" />}
                </div>
                <span>Message Routing</span>
              </div>
              <div className="flex items-center gap-2 text-sm">
                <div className={agent.mcpFeatures.toolUse ? "text-green-500" : "text-muted-foreground"}>
                  {agent.mcpFeatures.toolUse ? <Check className="h-4 w-4" /> : <span className="h-4 w-4 inline-block" />}
                </div>
                <span>Tool Use</span>
              </div>
              <div className="flex items-center gap-2 text-sm">
                <div className={agent.mcpFeatures.multiAgentCollaboration ? "text-green-500" : "text-muted-foreground"}>
                  {agent.mcpFeatures.multiAgentCollaboration ? <Check className="h-4 w-4" /> : <span className="h-4 w-4 inline-block" />}
                </div>
                <span>Multi-Agent</span>
              </div>
              <div className="flex items-center gap-2 text-sm">
                <div className={agent.mcpFeatures.humanInTheLoop ? "text-green-500" : "text-muted-foreground"}>
                  {agent.mcpFeatures.humanInTheLoop ? <Check className="h-4 w-4" /> : <span className="h-4 w-4 inline-block" />}
                </div>
                <span>Human-in-the-Loop</span>
              </div>
            </div>
            
            <div className="flex justify-between items-center mb-4">
              <div className="flex gap-4">
                <div className="flex items-center gap-1">
                  <Star className="h-4 w-4 text-yellow-500" />
                  <span className="text-sm">{agent.stats.rating}</span>
                </div>
                <div className="flex items-center gap-1">
                  <Users className="h-4 w-4 text-muted-foreground" />
                  <span className="text-sm text-muted-foreground">{agent.stats.users}</span>
                </div>
                <div className="flex items-center gap-1">
                  <BarChart2 className="h-4 w-4 text-muted-foreground" />
                  <span className="text-sm text-muted-foreground">{agent.stats.runs}</span>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <span className="font-bold">${agent.price}</span>
                <span className="text-sm text-muted-foreground">/mo</span>
              </div>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-sm text-muted-foreground">{agent.category}</span>
              <button className="text-primary hover:underline flex items-center gap-1">
                View Details
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
} 