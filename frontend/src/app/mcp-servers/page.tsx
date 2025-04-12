"use client";

import { useState } from "react";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Server, Download, Plus, Edit, Trash2, BarChart, Filter, LayoutGrid, Table as TableIcon } from "lucide-react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

// Sample MCP servers data for browse tab
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

// Sample data for published MCP servers
interface MCPServer {
  id: string;
  name: string;
  description: string;
  status: "published" | "pending" | "rejected";
  downloads: number;
  lastUpdated: string;
  isPublic: boolean;
}

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

export default function MCPServersPage() {
  const [searchQuery, setSearchQuery] = useState("");
  const [activeTab, setActiveTab] = useState("myservers");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [servers, setServers] = useState<MCPServer[]>(publishedServers);
  const [viewMode, setViewMode] = useState<"card" | "table">("card");

  const filteredServers = mcpServers.filter(server => 
    server.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    server.description.toLowerCase().includes(searchQuery.toLowerCase()) ||
    server.tags.some(tag => tag.toLowerCase().includes(searchQuery.toLowerCase()))
  );

  const filteredPublishedServers = servers.filter(server => 
    statusFilter === "all" || server.status === statusFilter
  );

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
  
  const toggleStatus = (serverId: string) => {
    // In a real app, this would call an API to update the server status
    setServers(prev => prev.map(server => {
      if (server.id === serverId) {
        return {
          ...server,
          status: server.status === "published" ? "pending" : "published"
        };
      }
      return server;
    }));
  };

  return (
    <div className="p-6">
      <Tabs defaultValue="myservers" className="w-full" onValueChange={(value) => setActiveTab(value)}>
        <div className="flex justify-between items-center mb-6">
          <TabsList>
            <TabsTrigger value="myservers">My Servers</TabsTrigger>
            <TabsTrigger value="browse">Browse Servers</TabsTrigger>
          </TabsList>
          <div className="flex items-center gap-4">
            {activeTab === "browse" && (
              <Input
                placeholder="Search MCP servers..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="max-w-md"
              />
            )}
            {activeTab === "myservers" && (
              <>
                <div className="flex items-center gap-2">
                  <Filter className="h-4 w-4 text-muted-foreground" />
                  <Select
                    value={statusFilter}
                    onValueChange={setStatusFilter}
                  >
                    <SelectTrigger className="w-[140px]">
                      <SelectValue placeholder="Filter status" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All Servers</SelectItem>
                      <SelectItem value="published">Published</SelectItem>
                      <SelectItem value="pending">Pending</SelectItem>
                      <SelectItem value="rejected">Rejected</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex rounded-md overflow-hidden shadow-sm">
                  <Button 
                    size="sm" 
                    variant={viewMode === "card" ? "default" : "outline"} 
                    className={`rounded-r-none ${viewMode === "card" ? "bg-blue-600 hover:bg-blue-700 text-white border-blue-600" : "border-r-0 hover:bg-blue-50 hover:text-blue-600 dark:hover:bg-blue-950 dark:hover:text-blue-400"}`} 
                    onClick={() => setViewMode("card")}
                  >
                    <LayoutGrid className="h-4 w-4 mr-1" />
                    Cards
                  </Button>
                  <Button 
                    size="sm" 
                    variant={viewMode === "table" ? "default" : "outline"} 
                    className={`rounded-l-none ${viewMode === "table" ? "bg-blue-600 hover:bg-blue-700 text-white border-blue-600" : "border-l-0 hover:bg-blue-50 hover:text-blue-600 dark:hover:bg-blue-950 dark:hover:text-blue-400"}`} 
                    onClick={() => setViewMode("table")}
                  >
                    <TableIcon className="h-4 w-4 mr-1" />
                    Table
                  </Button>
                </div>
              </>
            )}
            <Button asChild className="bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-700 hover:to-indigo-700 text-white shadow-md transition-all duration-200">
              <Link href="/mcp-servers/add" className="flex items-center gap-1">
                <Plus className="h-4 w-4" />
                Add MCP Server
              </Link>
            </Button>
          </div>
        </div>
        
        <TabsContent value="browse" className="mt-0">
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
        </TabsContent>
        
        <TabsContent value="myservers" className="mt-0">
          {filteredPublishedServers.length === 0 ? (
            <Card className="p-8 text-center">
              <p className="text-muted-foreground mb-4">
                {statusFilter === "all" 
                  ? "You haven't published any MCP servers yet."
                  : `You don't have any ${statusFilter} MCP servers.`}
              </p>
              <Button asChild className="bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-700 hover:to-indigo-700 text-white shadow-md transition-all duration-200">
                <Link href="/mcp-servers/add" className="flex items-center gap-1">
                  <Plus className="h-4 w-4" />
                  Add Your First Server
                </Link>
              </Button>
            </Card>
          ) : (
            <>
              {viewMode === "card" ? (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                  {filteredPublishedServers.map((server) => (
                    <Card key={server.id} className="flex flex-col">
                      <CardHeader className="pb-2">
                        <div className="flex justify-between items-start">
                          <div className="flex items-center gap-2">
                            <Server className="h-5 w-5 text-primary" />
                            <CardTitle className="text-xl">{server.name}</CardTitle>
                          </div>
                          <div className="flex items-center gap-3 bg-background/80 backdrop-blur-sm px-3 py-1 rounded-full border">
                            <Label htmlFor={`status-switch-${server.id}`} className={`text-sm font-medium ${server.status === "published" ? "text-green-600 dark:text-green-400" : "text-amber-600 dark:text-amber-400"}`}>
                              {server.status === "published" ? "Published" : "Draft"}
                            </Label>
                            <Switch
                              id={`status-switch-${server.id}`}
                              checked={server.status === "published"}
                              onCheckedChange={() => toggleStatus(server.id)}
                              className="data-[state=checked]:bg-green-500"
                            />
                          </div>
                        </div>
                        <CardDescription>{server.description}</CardDescription>
                      </CardHeader>
                      <CardContent className="flex-grow">
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
              ) : (
                <div className="rounded-md border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Name</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead>Downloads</TableHead>
                        <TableHead>Visibility</TableHead>
                        <TableHead>Last Updated</TableHead>
                        <TableHead className="text-right">Actions</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {filteredPublishedServers.map((server) => (
                        <TableRow key={server.id}>
                          <TableCell className="font-medium">
                            <div className="flex items-center gap-2">
                              <Server className="h-4 w-4 text-primary" />
                              {server.name}
                            </div>
                            <div className="text-xs text-muted-foreground mt-1 max-w-md truncate">
                              {server.description}
                            </div>
                          </TableCell>
                          <TableCell>
                            <div className="flex items-center gap-3 bg-background px-2 py-1 rounded-full inline-flex border">
                              <Label htmlFor={`table-status-${server.id}`} className={`text-xs font-medium ${server.status === "published" ? "text-green-600 dark:text-green-400" : "text-amber-600 dark:text-amber-400"}`}>
                                {server.status === "published" ? "Published" : "Draft"}
                              </Label>
                              <Switch
                                id={`table-status-${server.id}`}
                                checked={server.status === "published"}
                                onCheckedChange={() => toggleStatus(server.id)}
                                className="data-[state=checked]:bg-green-500 h-5 w-9"
                              />
                            </div>
                          </TableCell>
                          <TableCell>
                            <div className="flex items-center gap-1">
                              <Download className="h-4 w-4 text-muted-foreground" />
                              {server.downloads}
                            </div>
                          </TableCell>
                          <TableCell>{server.isPublic ? "Public" : "Private"}</TableCell>
                          <TableCell>{server.lastUpdated}</TableCell>
                          <TableCell className="text-right">
                            <div className="flex justify-end gap-2">
                              <Button variant="outline" size="sm" className="h-8 w-8 p-0">
                                <BarChart className="h-4 w-4" />
                                <span className="sr-only">Analytics</span>
                              </Button>
                              <Button variant="outline" size="sm" className="h-8 w-8 p-0">
                                <Edit className="h-4 w-4" />
                                <span className="sr-only">Edit</span>
                              </Button>
                              <Button variant="outline" size="sm" className="h-8 w-8 p-0 text-destructive hover:text-destructive hover:bg-destructive/10">
                                <Trash2 className="h-4 w-4" />
                                <span className="sr-only">Remove</span>
                              </Button>
                            </div>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
} 