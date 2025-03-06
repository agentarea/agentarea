"use client";

import React, { useState } from "react";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Bot,
  Search,
  Filter,
  ArrowUpDown,
  Star,
  Users,
  BarChart2,
  ChevronRight,
  Info
} from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

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
const sortOptions = ["Most Popular", "Highest Rated", "Newest", "Price: Low to High", "Price: High to Low"];

export default function MarketplaceBrowsePage() {
  const [isLoading, setIsLoading] = useState(false);
  const [selectedCategory, setSelectedCategory] = useState("All");
  const [searchQuery, setSearchQuery] = useState("");

  // Simulate loading state for demonstration
  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    // Simulate API call
    setTimeout(() => setIsLoading(false), 800);
  };

  return (
    <div className="container mx-auto px-4 py-8 max-w-7xl">
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-8">
        <div>
          <h1 className="text-3xl md:text-4xl font-bold tracking-tight">Marketplace</h1>
          <p className="text-base md:text-lg text-muted-foreground mt-2 max-w-2xl">
            Discover and deploy pre-built automation agents to streamline your workflow
          </p>
        </div>
        <Button className="hidden md:flex">
          Submit Agent
        </Button>
      </div>

      <form onSubmit={handleSearch} className="mb-6">
        <div className="flex flex-col sm:flex-row gap-4">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-muted-foreground h-4 w-4" />
            <Input
              placeholder="Search marketplace..."
              className="pl-10"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              aria-label="Search marketplace"
            />
          </div>
          <div className="flex gap-2">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" className="flex items-center gap-2">
                  <Filter className="h-4 w-4" />
                  <span className="hidden sm:inline">Filter</span>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-56">
                <DropdownMenuItem>Free Agents</DropdownMenuItem>
                <DropdownMenuItem>Premium Agents</DropdownMenuItem>
                <DropdownMenuItem>Verified Creators</DropdownMenuItem>
                <DropdownMenuItem>Recently Updated</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" className="flex items-center gap-2">
                  <ArrowUpDown className="h-4 w-4" />
                  <span className="hidden sm:inline">Sort</span>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-56">
                {sortOptions.map((option) => (
                  <DropdownMenuItem key={option}>{option}</DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
            
            <Button type="submit" className="sm:hidden">
              <Search className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </form>

      <div className="flex gap-2 mb-8 overflow-x-auto pb-2 scrollbar-thin scrollbar-thumb-rounded scrollbar-thumb-secondary">
        {categories.map((category) => (
          <Button
            key={category}
            variant={selectedCategory === category ? "default" : "secondary"}
            size="sm"
            className="rounded-full whitespace-nowrap"
            onClick={() => setSelectedCategory(category)}
          >
            {category}
          </Button>
        ))}
      </div>

      {isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {[1, 2, 3].map((i) => (
            <Card key={i} className="p-6 overflow-hidden">
              <div className="flex items-start gap-3 mb-4">
                <Skeleton className="h-12 w-12 rounded-lg" />
                <div className="space-y-2 flex-1">
                  <Skeleton className="h-5 w-3/4" />
                  <Skeleton className="h-4 w-1/2" />
                </div>
              </div>
              <Skeleton className="h-4 w-full mb-2" />
              <Skeleton className="h-4 w-5/6 mb-6" />
              <div className="flex justify-between mb-4">
                <div className="flex gap-4">
                  <Skeleton className="h-4 w-16" />
                  <Skeleton className="h-4 w-16" />
                  <Skeleton className="h-4 w-16" />
                </div>
                <Skeleton className="h-4 w-16" />
              </div>
              <div className="flex justify-between">
                <Skeleton className="h-4 w-24" />
                <Skeleton className="h-4 w-24" />
              </div>
            </Card>
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {agents.map((agent) => (
            <Card 
              key={agent.id} 
              className="p-6 hover:shadow-lg transition-all duration-300 cursor-pointer border border-border/40 hover:border-primary/20 focus-within:ring-2 focus-within:ring-primary/20 focus-within:ring-offset-2"
              tabIndex={0}
              role="article"
              aria-labelledby={`agent-title-${agent.id}`}
            >
              <div className="flex items-start justify-between mb-4">
                <div className="flex items-center gap-3">
                  <div className="h-12 w-12 bg-primary/10 rounded-lg flex items-center justify-center">
                    <Bot className="h-6 w-6 text-primary" />
                  </div>
                  <div>
                    <h3 id={`agent-title-${agent.id}`} className="font-semibold text-lg">{agent.name}</h3>
                    <span className="text-sm text-muted-foreground">by {agent.creator}</span>
                  </div>
                </div>
                <Badge variant="outline" className="text-xs">{agent.category}</Badge>
              </div>
              <p className="text-sm text-muted-foreground mb-6 line-clamp-2">{agent.description}</p>
              <div className="flex justify-between items-center mb-4">
                <div className="flex gap-4">
                  <TooltipProvider>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <div className="flex items-center gap-1">
                          <Star className="h-4 w-4 text-yellow-500" />
                          <span className="text-sm font-medium">{agent.stats.rating}</span>
                        </div>
                      </TooltipTrigger>
                      <TooltipContent>
                        <p>Average user rating</p>
                      </TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                  
                  <TooltipProvider>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <div className="flex items-center gap-1">
                          <Users className="h-4 w-4 text-muted-foreground" />
                          <span className="text-sm text-muted-foreground">{agent.stats.users.toLocaleString()}</span>
                        </div>
                      </TooltipTrigger>
                      <TooltipContent>
                        <p>Active users</p>
                      </TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                  
                  <TooltipProvider>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <div className="flex items-center gap-1">
                          <BarChart2 className="h-4 w-4 text-muted-foreground" />
                          <span className="text-sm text-muted-foreground">{agent.stats.runs.toLocaleString()}</span>
                        </div>
                      </TooltipTrigger>
                      <TooltipContent>
                        <p>Total executions</p>
                      </TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                </div>
                <div className="flex items-center gap-1">
                  <span className="font-bold">${agent.price}</span>
                  <span className="text-xs text-muted-foreground">/mo</span>
                </div>
              </div>
              <div className="flex justify-end">
                <Button variant="ghost" size="sm" className="text-primary hover:text-primary/80 hover:bg-primary/10 flex items-center gap-1 -mr-2">
                  View Details
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}
      
      {agents.length === 0 && !isLoading && (
        <div className="flex flex-col items-center justify-center py-12 text-center">
          <div className="rounded-full bg-muted p-3 mb-4">
            <Info className="h-6 w-6 text-muted-foreground" />
          </div>
          <h3 className="text-lg font-medium mb-1">No agents found</h3>
          <p className="text-muted-foreground max-w-md">
            We couldn&apos;t find any agents matching your search criteria. Try adjusting your filters or search query.
          </p>
        </div>
      )}
      
      <div className="mt-12 text-center">
        <p className="text-muted-foreground mb-4">Don&apos;t see what you&apos;re looking for?</p>
        <Button className="md:hidden">Submit Agent</Button>
      </div>
    </div>
  );
} 