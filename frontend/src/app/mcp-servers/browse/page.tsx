"use client";

import { useState } from "react";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Server, Download, Plus } from "lucide-react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";

// Sample MCP servers data (in a real app, this would come from an API)
const mcpServers = [
  {
    id: "1",
    name: "File System MCP",
    description: "Access local files through MCP protocol",
    author: "Anthropic",
    stars: 245,
    verified: true,
    tags: ["files", "local storage"],
  },
  {
    id: "2",
    name: "Web Search MCP",
    description: "Browse the web and fetch up-to-date information",
    author: "Community",
    stars: 186,
    verified: false,
    tags: ["web", "search"],
  },
  {
    id: "3",
    name: "Database MCP",
    description: "Connect to SQL and NoSQL databases",
    author: "AgentMesh",
    stars: 152,
    verified: true,
    tags: ["database", "sql", "nosql"],
  },
];

export default function BrowseMCPServersPage() {
  const [searchQuery, setSearchQuery] = useState("");
  
  const filteredServers = mcpServers.filter(server => 
    server.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    server.description.toLowerCase().includes(searchQuery.toLowerCase()) ||
    server.tags.some(tag => tag.toLowerCase().includes(searchQuery.toLowerCase()))
  );
  
  return (
    <div className="p-6">
      <div className="flex justify-between items-center mb-6">
        <Input
          placeholder="Search MCP servers..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="max-w-md"
        />
        <Button asChild>
          <Link href="/marketplace/mcp-servers/add" className="flex items-center gap-1">
            <Plus className="h-4 w-4" />
            Add MCP Server
          </Link>
        </Button>
      </div>
      
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {filteredServers.map((server) => (
          <Card key={server.id} className="flex flex-col">
            <CardHeader>
              <div className="flex justify-between items-start">
                <div className="flex items-center gap-2">
                  <Server className="h-5 w-5 text-primary" />
                  <CardTitle>{server.name}</CardTitle>
                </div>
                {server.verified && (
                  <Badge variant="secondary">Verified</Badge>
                )}
              </div>
              <CardDescription>{server.description}</CardDescription>
            </CardHeader>
            <CardContent className="flex-grow">
              <div className="flex flex-wrap gap-2 mb-3">
                {server.tags.map((tag) => (
                  <Badge key={tag} variant="outline">{tag}</Badge>
                ))}
              </div>
              <p className="text-sm text-muted-foreground">By {server.author} • {server.stars} stars</p>
            </CardContent>
            <CardFooter className="flex justify-between">
              <Button variant="outline" size="sm">View Details</Button>
              <Button size="sm" className="flex items-center gap-1">
                <Download className="h-4 w-4" />
                Install
              </Button>
            </CardFooter>
          </Card>
        ))}
      </div>
    </div>
  );
} 