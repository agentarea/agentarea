"use client";

import React, { useState } from "react";
import { Card } from "@/components/ui/card";
import { 
  Building2, 
  Users, 
  Bot, 
  Database, 
  Wrench, 
  Server,
  Plus,
  ChevronRight,
  Lock,
  Globe,
  Shield,
  Settings
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

interface Scope {
  id: string;
  name: string;
  description: string;
  type: "project" | "team" | "department";
  resources: {
    agents: string[];
    sources: string[];
    tools: string[];
    mcps: string[];
  };
  permissions: {
    read: boolean;
    write: boolean;
    admin: boolean;
  };
  members: string[];
  createdAt: string;
}

export default function ScopesPage() {
  const [scopes, setScopes] = useState<Scope[]>([
    {
      id: "scope-1",
      name: "Marketing Campaign",
      description: "Q2 Marketing Campaign Project",
      type: "project",
      resources: {
        agents: ["Marketing Analytics Agent", "Content Generator"],
        sources: ["Social Media API", "Analytics Database"],
        tools: ["Social Media Manager", "Content Calendar"],
        mcps: ["Marketing MCP"]
      },
      permissions: {
        read: true,
        write: true,
        admin: false
      },
      members: ["John Doe", "Jane Smith"],
      createdAt: "2 days ago"
    },
    {
      id: "scope-2",
      name: "Development Team",
      description: "Core Development Team",
      type: "team",
      resources: {
        agents: ["Code Review Agent", "Testing Agent"],
        sources: ["GitHub", "Jira"],
        tools: ["GitHub Integration", "CI/CD Pipeline"],
        mcps: ["DevOps MCP"]
      },
      permissions: {
        read: true,
        write: true,
        admin: true
      },
      members: ["Alice Johnson", "Bob Wilson"],
      createdAt: "1 week ago"
    }
  ]);

  const [activeTab, setActiveTab] = useState<string>("all");
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [newScope, setNewScope] = useState<Partial<Scope>>({
    type: "project",
    permissions: {
      read: true,
      write: false,
      admin: false
    }
  });

  const getScopeIcon = (type: Scope["type"]) => {
    switch(type) {
      case "project": return <Globe className="h-4 w-4" />;
      case "team": return <Users className="h-4 w-4" />;
      case "department": return <Building2 className="h-4 w-4" />;
    }
  };

  const getScopeColor = (type: Scope["type"]) => {
    switch(type) {
      case "project": return "text-blue-500";
      case "team": return "text-green-500";
      case "department": return "text-purple-500";
    }
  };

  const handleCreateScope = () => {
    if (!newScope.name || !newScope.description) return;

    const scope: Scope = {
      id: `scope-${Date.now()}`,
      name: newScope.name,
      description: newScope.description,
      type: newScope.type as Scope["type"],
      resources: {
        agents: [],
        sources: [],
        tools: [],
        mcps: []
      },
      permissions: newScope.permissions as Scope["permissions"],
      members: [],
      createdAt: "Just now"
    };

    setScopes([...scopes, scope]);
    setShowCreateDialog(false);
    setNewScope({
      type: "project",
      permissions: {
        read: true,
        write: false,
        admin: false
      }
    });
  };

  return (
    <div className="min-h-screen bg-gradient-to-b from-background to-muted/20">
      <div className="p-8 max-w-7xl mx-auto">
        <div className="mb-12">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-4xl font-bold tracking-tight bg-gradient-to-r from-primary to-primary/60 bg-clip-text text-transparent">
                Scopes
              </h1>
              <p className="text-lg text-muted-foreground mt-2">
                Create and manage organizational scopes for projects, teams, and departments
              </p>
            </div>
            <Dialog open={showCreateDialog} onOpenChange={setShowCreateDialog}>
              <DialogTrigger asChild>
                <Button className="gap-2">
                  <Plus className="h-4 w-4" />
                  Create Scope
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>Create New Scope</DialogTitle>
                  <DialogDescription>
                    Define a new organizational scope for managing resources and permissions.
                  </DialogDescription>
                </DialogHeader>
                <div className="space-y-4 py-4">
                  <div className="space-y-2">
                    <label className="text-sm font-medium">Name</label>
                    <Input
                      placeholder="Enter scope name"
                      value={newScope.name || ""}
                      onChange={(e) => setNewScope({ ...newScope, name: e.target.value })}
                    />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium">Description</label>
                    <Input
                      placeholder="Enter scope description"
                      value={newScope.description || ""}
                      onChange={(e) => setNewScope({ ...newScope, description: e.target.value })}
                    />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium">Type</label>
                    <Select
                      value={newScope.type}
                      onValueChange={(value) => setNewScope({ ...newScope, type: value as Scope["type"] })}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="Select scope type" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="project">Project</SelectItem>
                        <SelectItem value="team">Team</SelectItem>
                        <SelectItem value="department">Department</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium">Permissions</label>
                    <div className="space-y-2">
                      <div className="flex items-center gap-2">
                        <input
                          type="checkbox"
                          checked={newScope.permissions?.read}
                          onChange={(e) => setNewScope({
                            ...newScope,
                            permissions: { ...newScope.permissions!, read: e.target.checked }
                          })}
                        />
                        <label className="text-sm">Read Access</label>
                      </div>
                      <div className="flex items-center gap-2">
                        <input
                          type="checkbox"
                          checked={newScope.permissions?.write}
                          onChange={(e) => setNewScope({
                            ...newScope,
                            permissions: { ...newScope.permissions!, write: e.target.checked }
                          })}
                        />
                        <label className="text-sm">Write Access</label>
                      </div>
                      <div className="flex items-center gap-2">
                        <input
                          type="checkbox"
                          checked={newScope.permissions?.admin}
                          onChange={(e) => setNewScope({
                            ...newScope,
                            permissions: { ...newScope.permissions!, admin: e.target.checked }
                          })}
                        />
                        <label className="text-sm">Admin Access</label>
                      </div>
                    </div>
                  </div>
                </div>
                <DialogFooter>
                  <Button variant="outline" onClick={() => setShowCreateDialog(false)}>
                    Cancel
                  </Button>
                  <Button onClick={handleCreateScope}>
                    Create Scope
                  </Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          </div>
        </div>

        <Tabs defaultValue="all" className="w-full" value={activeTab} onValueChange={setActiveTab}>
          <div className="flex justify-between items-center mb-6">
            <TabsList className="grid w-full max-w-md grid-cols-3 bg-muted/50 p-1">
              <TabsTrigger value="all" className="rounded-md data-[state=active]:bg-background data-[state=active]:shadow-sm">
                <div className="flex items-center gap-2">
                  <Globe className="h-4 w-4" />
                  <span>All Scopes</span>
                </div>
              </TabsTrigger>
              <TabsTrigger value="projects" className="rounded-md data-[state=active]:bg-background data-[state=active]:shadow-sm">
                <div className="flex items-center gap-2">
                  <Globe className="h-4 w-4" />
                  <span>Projects</span>
                </div>
              </TabsTrigger>
              <TabsTrigger value="teams" className="rounded-md data-[state=active]:bg-background data-[state=active]:shadow-sm">
                <div className="flex items-center gap-2">
                  <Users className="h-4 w-4" />
                  <span>Teams</span>
                </div>
              </TabsTrigger>
            </TabsList>
          </div>

          <TabsContent value="all" className="mt-0">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {scopes.map((scope) => (
                <Card key={scope.id} className="p-6 border-none shadow-lg bg-gradient-to-b from-background to-muted/20">
                  <div className="flex items-start justify-between mb-4">
                    <div className="flex items-center gap-2">
                      <div className={getScopeColor(scope.type)}>
                        {getScopeIcon(scope.type)}
                      </div>
                      <h3 className="font-semibold">{scope.name}</h3>
                    </div>
                    <Badge variant="outline" className="text-xs">
                      {scope.type}
                    </Badge>
                  </div>
                  <p className="text-sm text-muted-foreground mb-4">{scope.description}</p>
                  
                  <div className="space-y-4">
                    <div>
                      <h4 className="text-sm font-medium mb-2">Resources</h4>
                      <div className="space-y-2">
                        {scope.resources.agents.length > 0 && (
                          <div className="flex items-center gap-2 text-sm">
                            <Bot className="h-4 w-4 text-blue-500" />
                            <span>{scope.resources.agents.length} Agents</span>
                          </div>
                        )}
                        {scope.resources.sources.length > 0 && (
                          <div className="flex items-center gap-2 text-sm">
                            <Database className="h-4 w-4 text-green-500" />
                            <span>{scope.resources.sources.length} Sources</span>
                          </div>
                        )}
                        {scope.resources.tools.length > 0 && (
                          <div className="flex items-center gap-2 text-sm">
                            <Wrench className="h-4 w-4 text-purple-500" />
                            <span>{scope.resources.tools.length} Tools</span>
                          </div>
                        )}
                        {scope.resources.mcps.length > 0 && (
                          <div className="flex items-center gap-2 text-sm">
                            <Server className="h-4 w-4 text-orange-500" />
                            <span>{scope.resources.mcps.length} MCPs</span>
                          </div>
                        )}
                      </div>
                    </div>

                    <div>
                      <h4 className="text-sm font-medium mb-2">Permissions</h4>
                      <div className="space-y-1">
                        {scope.permissions.read && (
                          <div className="flex items-center gap-2 text-sm">
                            <Lock className="h-4 w-4 text-muted-foreground" />
                            <span>Read Access</span>
                          </div>
                        )}
                        {scope.permissions.write && (
                          <div className="flex items-center gap-2 text-sm">
                            <Lock className="h-4 w-4 text-muted-foreground" />
                            <span>Write Access</span>
                          </div>
                        )}
                        {scope.permissions.admin && (
                          <div className="flex items-center gap-2 text-sm">
                            <Shield className="h-4 w-4 text-muted-foreground" />
                            <span>Admin Access</span>
                          </div>
                        )}
                      </div>
                    </div>

                    <div className="flex items-center justify-between pt-4 border-t">
                      <div className="flex items-center gap-2 text-sm text-muted-foreground">
                        <Users className="h-4 w-4" />
                        <span>{scope.members.length} Members</span>
                      </div>
                      <Button variant="ghost" size="sm" className="gap-1">
                        <Settings className="h-4 w-4" />
                        Manage
                      </Button>
                    </div>
                  </div>
                </Card>
              ))}
            </div>
          </TabsContent>

          <TabsContent value="projects" className="mt-0">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {scopes.filter(scope => scope.type === "project").map((scope) => (
                <Card key={scope.id} className="p-6 border-none shadow-lg bg-gradient-to-b from-background to-muted/20">
                  <div className="flex items-start justify-between mb-4">
                    <div className="flex items-center gap-2">
                      <div className={getScopeColor(scope.type)}>
                        {getScopeIcon(scope.type)}
                      </div>
                      <h3 className="font-semibold">{scope.name}</h3>
                    </div>
                    <Badge variant="outline" className="text-xs">
                      {scope.type}
                    </Badge>
                  </div>
                  <p className="text-sm text-muted-foreground mb-4">{scope.description}</p>
                  
                  <div className="space-y-4">
                    <div>
                      <h4 className="text-sm font-medium mb-2">Resources</h4>
                      <div className="space-y-2">
                        {scope.resources.agents.length > 0 && (
                          <div className="flex items-center gap-2 text-sm">
                            <Bot className="h-4 w-4 text-blue-500" />
                            <span>{scope.resources.agents.length} Agents</span>
                          </div>
                        )}
                        {scope.resources.sources.length > 0 && (
                          <div className="flex items-center gap-2 text-sm">
                            <Database className="h-4 w-4 text-green-500" />
                            <span>{scope.resources.sources.length} Sources</span>
                          </div>
                        )}
                        {scope.resources.tools.length > 0 && (
                          <div className="flex items-center gap-2 text-sm">
                            <Wrench className="h-4 w-4 text-purple-500" />
                            <span>{scope.resources.tools.length} Tools</span>
                          </div>
                        )}
                        {scope.resources.mcps.length > 0 && (
                          <div className="flex items-center gap-2 text-sm">
                            <Server className="h-4 w-4 text-orange-500" />
                            <span>{scope.resources.mcps.length} MCPs</span>
                          </div>
                        )}
                      </div>
                    </div>

                    <div>
                      <h4 className="text-sm font-medium mb-2">Permissions</h4>
                      <div className="space-y-1">
                        {scope.permissions.read && (
                          <div className="flex items-center gap-2 text-sm">
                            <Lock className="h-4 w-4 text-muted-foreground" />
                            <span>Read Access</span>
                          </div>
                        )}
                        {scope.permissions.write && (
                          <div className="flex items-center gap-2 text-sm">
                            <Lock className="h-4 w-4 text-muted-foreground" />
                            <span>Write Access</span>
                          </div>
                        )}
                        {scope.permissions.admin && (
                          <div className="flex items-center gap-2 text-sm">
                            <Shield className="h-4 w-4 text-muted-foreground" />
                            <span>Admin Access</span>
                          </div>
                        )}
                      </div>
                    </div>

                    <div className="flex items-center justify-between pt-4 border-t">
                      <div className="flex items-center gap-2 text-sm text-muted-foreground">
                        <Users className="h-4 w-4" />
                        <span>{scope.members.length} Members</span>
                      </div>
                      <Button variant="ghost" size="sm" className="gap-1">
                        <Settings className="h-4 w-4" />
                        Manage
                      </Button>
                    </div>
                  </div>
                </Card>
              ))}
            </div>
          </TabsContent>

          <TabsContent value="teams" className="mt-0">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {scopes.filter(scope => scope.type === "team").map((scope) => (
                <Card key={scope.id} className="p-6 border-none shadow-lg bg-gradient-to-b from-background to-muted/20">
                  <div className="flex items-start justify-between mb-4">
                    <div className="flex items-center gap-2">
                      <div className={getScopeColor(scope.type)}>
                        {getScopeIcon(scope.type)}
                      </div>
                      <h3 className="font-semibold">{scope.name}</h3>
                    </div>
                    <Badge variant="outline" className="text-xs">
                      {scope.type}
                    </Badge>
                  </div>
                  <p className="text-sm text-muted-foreground mb-4">{scope.description}</p>
                  
                  <div className="space-y-4">
                    <div>
                      <h4 className="text-sm font-medium mb-2">Resources</h4>
                      <div className="space-y-2">
                        {scope.resources.agents.length > 0 && (
                          <div className="flex items-center gap-2 text-sm">
                            <Bot className="h-4 w-4 text-blue-500" />
                            <span>{scope.resources.agents.length} Agents</span>
                          </div>
                        )}
                        {scope.resources.sources.length > 0 && (
                          <div className="flex items-center gap-2 text-sm">
                            <Database className="h-4 w-4 text-green-500" />
                            <span>{scope.resources.sources.length} Sources</span>
                          </div>
                        )}
                        {scope.resources.tools.length > 0 && (
                          <div className="flex items-center gap-2 text-sm">
                            <Wrench className="h-4 w-4 text-purple-500" />
                            <span>{scope.resources.tools.length} Tools</span>
                          </div>
                        )}
                        {scope.resources.mcps.length > 0 && (
                          <div className="flex items-center gap-2 text-sm">
                            <Server className="h-4 w-4 text-orange-500" />
                            <span>{scope.resources.mcps.length} MCPs</span>
                          </div>
                        )}
                      </div>
                    </div>

                    <div>
                      <h4 className="text-sm font-medium mb-2">Permissions</h4>
                      <div className="space-y-1">
                        {scope.permissions.read && (
                          <div className="flex items-center gap-2 text-sm">
                            <Lock className="h-4 w-4 text-muted-foreground" />
                            <span>Read Access</span>
                          </div>
                        )}
                        {scope.permissions.write && (
                          <div className="flex items-center gap-2 text-sm">
                            <Lock className="h-4 w-4 text-muted-foreground" />
                            <span>Write Access</span>
                          </div>
                        )}
                        {scope.permissions.admin && (
                          <div className="flex items-center gap-2 text-sm">
                            <Shield className="h-4 w-4 text-muted-foreground" />
                            <span>Admin Access</span>
                          </div>
                        )}
                      </div>
                    </div>

                    <div className="flex items-center justify-between pt-4 border-t">
                      <div className="flex items-center gap-2 text-sm text-muted-foreground">
                        <Users className="h-4 w-4" />
                        <span>{scope.members.length} Members</span>
                      </div>
                      <Button variant="ghost" size="sm" className="gap-1">
                        <Settings className="h-4 w-4" />
                        Manage
                      </Button>
                    </div>
                  </div>
                </Card>
              ))}
            </div>
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
} 