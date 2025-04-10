"use client";

import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Server, Edit, Trash2, BarChart, Download, Plus } from "lucide-react";
import Link from "next/link";

interface MCPServer {
  id: string;
  name: string;
  description: string;
  status: "published" | "pending" | "rejected";
  downloads: number;
  lastUpdated: string;
  isPublic: boolean;
}

// Sample data for published MCP servers
const publishedServers: MCPServer[] = [
  {
    id: "1",
    name: "SQL Database MCP",
    description: "Connect to SQL databases through MCP protocol",
    status: "published",
    downloads: 152,
    lastUpdated: "2023-12-15",
    isPublic: true,
  },
  {
    id: "2",
    name: "Github MCP",
    description: "Access GitHub repositories and data through MCP",
    status: "pending",
    downloads: 0,
    lastUpdated: "2024-03-28",
    isPublic: true,
  },
  {
    id: "3",
    name: "Custom API MCP",
    description: "Connect to your custom APIs through MCP protocol",
    status: "published",
    downloads: 47,
    lastUpdated: "2024-02-10",
    isPublic: false,
  },
];

export default function PublishedMCPServersPage() {
  const getStatusBadge = (status: MCPServer["status"]) => {
    switch (status) {
      case "published":
        return <Badge className="bg-green-500">Published</Badge>;
      case "pending":
        return <Badge variant="outline" className="text-yellow-600 border-yellow-600">Pending Review</Badge>;
      case "rejected":
        return <Badge variant="destructive">Rejected</Badge>;
      default:
        return null;
    }
  };

  return (
    <div className="p-6">
      <div className="flex justify-end mb-6">
        <Button asChild>
          <Link href="/marketplace/mcp-servers/add" className="flex items-center gap-1">
            <Plus className="h-4 w-4" />
            Add MCP Server
          </Link>
        </Button>
      </div>
      
      {publishedServers.length === 0 ? (
        <Card className="p-8 text-center">
          <p className="text-muted-foreground mb-4">You haven't published any MCP servers yet.</p>
          <Button asChild>
            <Link href="/marketplace/mcp-servers/add" className="flex items-center gap-1">
              <Plus className="h-4 w-4" />
              Add Your First Server
            </Link>
          </Button>
        </Card>
      ) : (
        <div className="space-y-4">
          {publishedServers.map((server) => (
            <Card key={server.id} className="overflow-hidden">
              <CardHeader className="pb-2">
                <div className="flex justify-between items-start">
                  <div className="flex items-center gap-2">
                    <Server className="h-5 w-5 text-primary" />
                    <CardTitle className="text-xl">{server.name}</CardTitle>
                  </div>
                  {getStatusBadge(server.status)}
                </div>
                <CardDescription>{server.description}</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
                  <div className="flex items-center gap-1">
                    <Download className="h-4 w-4 text-muted-foreground" />
                    <span>{server.downloads} downloads</span>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Visibility: </span>
                    <span>{server.isPublic ? "Public" : "Private"}</span>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Last updated: </span>
                    <span>{server.lastUpdated}</span>
                  </div>
                </div>
              </CardContent>
              <CardFooter className="bg-muted/40 flex justify-end gap-2 py-3">
                <Button variant="outline" size="sm" className="flex items-center gap-1">
                  <BarChart className="h-4 w-4" />
                  Analytics
                </Button>
                <Button variant="outline" size="sm" className="flex items-center gap-1">
                  <Edit className="h-4 w-4" />
                  Edit
                </Button>
                <Button variant="outline" size="sm" className="flex items-center gap-1 text-destructive hover:text-destructive hover:bg-destructive/10">
                  <Trash2 className="h-4 w-4" />
                  Remove
                </Button>
              </CardFooter>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
} 