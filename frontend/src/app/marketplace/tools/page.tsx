"use client";

import React, { useState } from "react";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { 
  Wrench, 
  Plus, 
  Filter, 
  Settings, 
  MoreVertical, 
  Share2, 
  User, 
  Users, 
  Lock, 
  Globe,
  Database,
  FileJson
} from "lucide-react";
import Link from "next/link";

interface Tool {
  id: string;
  name: string;
  description: string;
  category: string;
  accessLevel: "private" | "team" | "organization" | "public";
  dataSources: string[];
  modelCompatibility: string[];
  createdBy: string;
  createdAt: string;
}

export default function ToolsListPage() {
  const [searchQuery, setSearchQuery] = useState("");
  const [activeFilter, setActiveFilter] = useState("all");
  const [activeCategory, setActiveCategory] = useState("all");
  
  // Mock data for tools
  const tools: Tool[] = [
    {
      id: "1",
      name: "Web Search",
      description: "Search the web for real-time information",
      category: "data-retrieval",
      accessLevel: "organization",
      dataSources: ["web"],
      modelCompatibility: ["OpenAI", "Anthropic", "Gemini"],
      createdBy: "Admin",
      createdAt: "2023-12-01"
    },
    {
      id: "2",
      name: "Document Analyzer",
      description: "Extract and analyze information from documents",
      category: "data-processing",
      accessLevel: "team",
      dataSources: ["document-store"],
      modelCompatibility: ["OpenAI", "Anthropic"],
      createdBy: "Data Team",
      createdAt: "2024-01-15"
    },
    {
      id: "3",
      name: "Code Generator",
      description: "Generate code snippets based on requirements",
      category: "development",
      accessLevel: "public",
      dataSources: ["code-repository"],
      modelCompatibility: ["OpenAI", "Anthropic", "Gemini", "Llama"],
      createdBy: "Dev Team",
      createdAt: "2024-02-10"
    },
    {
      id: "4",
      name: "Data Connector",
      description: "Connect to external databases and fetch information",
      category: "data-retrieval",
      accessLevel: "private",
      dataSources: ["database", "api"],
      modelCompatibility: ["OpenAI", "Anthropic"],
      createdBy: "You",
      createdAt: "2024-03-05"
    }
  ];

  // Filter tools based on search query, access level and category
  const filteredTools = tools.filter(tool => {
    const matchesSearch = tool.name.toLowerCase().includes(searchQuery.toLowerCase()) || 
                         tool.description.toLowerCase().includes(searchQuery.toLowerCase());
    
    const matchesAccessLevel = activeFilter === "all" || 
                             (activeFilter === "my" && tool.createdBy === "You") ||
                             (activeFilter === tool.accessLevel);
    
    const matchesCategory = activeCategory === "all" || tool.category === activeCategory;
    
    return matchesSearch && matchesAccessLevel && matchesCategory;
  });

  const getAccessLevelIcon = (level: Tool["accessLevel"]) => {
    switch (level) {
      case "private": return <User className="h-4 w-4" />;
      case "team": return <Users className="h-4 w-4" />;
      case "organization": return <Lock className="h-4 w-4" />;
      case "public": return <Globe className="h-4 w-4" />;
    }
  };

  return (
    <div className="p-8">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-4xl font-bold flex items-center gap-3">
            <Wrench className="h-8 w-8" />
            Tools Marketplace
          </h1>
          <p className="text-lg text-muted-foreground mt-2">
            Discover, manage, and create tools for your agents
          </p>
        </div>
        <Link href="/marketplace/tools/create">
          <Button className="flex items-center gap-2">
            <Plus className="h-4 w-4" />
            Create Tool
          </Button>
        </Link>
      </div>

      <div className="flex items-center gap-4 mb-6">
        <div className="relative flex-1">
          <Input
            placeholder="Search tools..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-10"
          />
          <div className="absolute left-3 top-1/2 transform -translate-y-1/2">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              className="h-5 w-5 text-muted-foreground"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
              />
            </svg>
          </div>
        </div>

        <Select value={activeCategory} onValueChange={setActiveCategory}>
          <SelectTrigger className="w-[180px]">
            <SelectValue placeholder="Category" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Categories</SelectItem>
            <SelectItem value="data-retrieval">Data Retrieval</SelectItem>
            <SelectItem value="data-processing">Data Processing</SelectItem>
            <SelectItem value="development">Development</SelectItem>
          </SelectContent>
        </Select>

        <Button variant="outline" className="flex items-center gap-2">
          <Filter className="h-4 w-4" />
          More Filters
        </Button>
      </div>

      <Tabs value={activeFilter} onValueChange={setActiveFilter} className="mb-6">
        <TabsList>
          <TabsTrigger value="all">All Tools</TabsTrigger>
          <TabsTrigger value="my">My Tools</TabsTrigger>
          <TabsTrigger value="organization">Organization</TabsTrigger>
          <TabsTrigger value="team">Team</TabsTrigger>
          <TabsTrigger value="public">Public</TabsTrigger>
        </TabsList>
      </Tabs>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {filteredTools.map((tool) => (
          <Card key={tool.id} className="overflow-hidden">
            <CardHeader className="pb-2">
              <div className="flex justify-between items-start">
                <div>
                  <CardTitle className="text-xl">{tool.name}</CardTitle>
                  <CardDescription className="line-clamp-2">{tool.description}</CardDescription>
                </div>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button variant="ghost" size="icon">
                      <MoreVertical className="h-4 w-4" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem>
                      <Settings className="h-4 w-4 mr-2" />
                      Configure
                    </DropdownMenuItem>
                    <DropdownMenuItem>
                      <Share2 className="h-4 w-4 mr-2" />
                      Share
                    </DropdownMenuItem>
                    <DropdownMenuItem>
                      <FileJson className="h-4 w-4 mr-2" />
                      View Schema
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            </CardHeader>
            <CardContent className="pb-4">
              <div className="flex gap-2 mb-3">
                <Badge variant="outline" className="flex items-center gap-1">
                  {getAccessLevelIcon(tool.accessLevel)}
                  {tool.accessLevel.charAt(0).toUpperCase() + tool.accessLevel.slice(1)}
                </Badge>
                <Badge variant="secondary">
                  {tool.category === "data-retrieval" ? "Data Retrieval" : 
                   tool.category === "data-processing" ? "Data Processing" : 
                   tool.category === "development" ? "Development" : tool.category}
                </Badge>
              </div>
              <div className="flex flex-col gap-2 text-sm">
                <div className="flex items-center gap-2">
                  <Database className="h-4 w-4 text-muted-foreground" />
                  <span className="text-muted-foreground">
                    {tool.dataSources.length > 1 
                      ? `${tool.dataSources[0]} + ${tool.dataSources.length - 1} more` 
                      : tool.dataSources[0]}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <svg className="h-4 w-4 text-muted-foreground" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M12 16C14.2091 16 16 14.2091 16 12C16 9.79086 14.2091 8 12 8C9.79086 8 8 9.79086 8 12C8 14.2091 9.79086 16 12 16Z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                    <path d="M3 12H8M16 12H21" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                    <path d="M12 3V8M12 16V21" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                  <span className="text-muted-foreground">
                    {tool.modelCompatibility.length > 2 
                      ? `${tool.modelCompatibility.slice(0, 2).join(", ")} + ${tool.modelCompatibility.length - 2} more` 
                      : tool.modelCompatibility.join(", ")}
                  </span>
                </div>
              </div>
            </CardContent>
            <CardFooter className="bg-muted/50 pt-2 pb-2 px-6 flex justify-between items-center">
              <span className="text-xs text-muted-foreground">
                Created by {tool.createdBy}
              </span>
              <Button variant="ghost" size="sm">Configure</Button>
            </CardFooter>
          </Card>
        ))}
      </div>

      {filteredTools.length === 0 && (
        <div className="text-center py-12">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-muted mb-4">
            <Wrench className="h-6 w-6 text-muted-foreground" />
          </div>
          <h3 className="text-lg font-medium">No tools found</h3>
          <p className="text-muted-foreground mt-1">
            Try adjusting your search or filters, or create a new tool.
          </p>
          <Link href="/marketplace/tools/create">
            <Button className="mt-4 flex items-center gap-2">
              <Plus className="h-4 w-4" />
              Create Tool
            </Button>
          </Link>
        </div>
      )}
    </div>
  );
} 