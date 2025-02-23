"use client";

import React from "react";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Bot,
  Search,
  Filter,
  ArrowUpDown,
  Star,
  Users,
  BarChart2,
  ChevronRight
} from "lucide-react";

interface MarketplaceAgent {
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
  category: string;
}

const agents: MarketplaceAgent[] = [
  {
    id: "agent-1",
    name: "E-commerce Assistant Pro",
    description: "Advanced AI assistant for handling customer inquiries and product recommendations",
    creator: "AgentMesh",
    price: 49.99,
    stats: {
      rating: 4.8,
      users: 1234,
      runs: 45678
    },
    category: "Customer Service"
  },
  {
    id: "agent-2",
    name: "Data Analysis Suite",
    description: "Comprehensive data analysis and visualization toolkit",
    creator: "DataWizards Inc",
    price: 79.99,
    stats: {
      rating: 4.6,
      users: 567,
      runs: 12345
    },
    category: "Analytics"
  },
  {
    id: "agent-3",
    name: "Document Processor",
    description: "Intelligent document processing and information extraction",
    creator: "DocTech",
    price: 29.99,
    stats: {
      rating: 4.7,
      users: 890,
      runs: 23456
    },
    category: "Document Processing"
  }
];

const categories = ["All", "Customer Service", "Analytics", "Document Processing", "Integration", "Automation"];

export default function MarketplaceBrowsePage() {
  return (
    <div className="p-8">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-4xl font-bold">Marketplace</h1>
          <p className="text-lg text-muted-foreground mt-2">
            Discover and deploy pre-built automation agents
          </p>
        </div>
      </div>

      <div className="flex gap-4 mb-6">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-muted-foreground h-4 w-4" />
          <Input
            placeholder="Search marketplace..."
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
        {agents.map((agent) => (
          <Card key={agent.id} className="p-6 hover:shadow-lg transition-shadow cursor-pointer">
            <div className="flex items-start justify-between mb-4">
              <div className="flex items-center gap-3">
                <div className="h-12 w-12 bg-primary/10 rounded-lg flex items-center justify-center">
                  <Bot className="h-6 w-6 text-primary" />
                </div>
                <div>
                  <h3 className="font-semibold">{agent.name}</h3>
                  <span className="text-sm text-muted-foreground">by {agent.creator}</span>
                </div>
              </div>
            </div>
            <p className="text-sm text-muted-foreground mb-4">{agent.description}</p>
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