"use client";

import React, { useState } from "react";
import { Card } from "@/components/ui/card";
import { 
  Bot, 
  Database, 
  FileText, 
  Globe, 
  Shield,
  Users,
  Search,
  Plus,
  Check,
  X,
  Edit,
  Trash2,
  ChevronRight,
  ChevronDown
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";

interface Team {
  id: string;
  name: string;
}

interface Resource {
  id: string;
  name: string;
  type: "agent" | "database" | "document" | "api";
  description: string;
  accessLevel: "read" | "write" | "admin" | "none";
  teams: string[];
}

const teams: Team[] = [
  { id: "team-1", name: "Customer Support" },
  { id: "team-2", name: "Data Analytics" },
  { id: "team-3", name: "Integration" },
];

const resources: Resource[] = [
  {
    id: "resource-1",
    name: "Customer Support Agent",
    type: "agent",
    description: "AI agent for handling customer inquiries",
    accessLevel: "admin",
    teams: ["Customer Support"]
  },
  {
    id: "resource-2",
    name: "Analytics Dashboard",
    type: "agent",
    description: "Agent for generating analytics reports",
    accessLevel: "write",
    teams: ["Data Analytics"]
  },
  {
    id: "resource-3",
    name: "Customer Database",
    type: "database",
    description: "Database containing customer information",
    accessLevel: "read",
    teams: ["Customer Support", "Data Analytics"]
  },
  {
    id: "resource-4",
    name: "Integration API",
    type: "api",
    description: "API for third-party integrations",
    accessLevel: "admin",
    teams: ["Integration"]
  },
  {
    id: "resource-5",
    name: "Documentation Repository",
    type: "document",
    description: "Repository for product documentation",
    accessLevel: "write",
    teams: ["Customer Support", "Integration"]
  },
];

const accessLevelColors: Record<string, string> = {
  "read": "bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400 border-blue-200 dark:border-blue-800",
  "write": "bg-green-50 text-green-700 dark:bg-green-900/30 dark:text-green-400 border-green-200 dark:border-green-800",
  "admin": "bg-purple-50 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400 border-purple-200 dark:border-purple-800",
  "none": "bg-gray-50 text-gray-700 dark:bg-gray-900/30 dark:text-gray-400 border-gray-200 dark:border-gray-800",
};

export default function TeamResourcesPage() {
  const [selectedTeam, setSelectedTeam] = useState<string>("all");
  const [expandedResource, setExpandedResource] = useState<string | null>(null);
  
  const filteredResources = selectedTeam === "all" 
    ? resources 
    : resources.filter(resource => resource.teams.includes(
        teams.find(team => team.id === selectedTeam)?.name || ""
      ));

  const getResourceIcon = (type: string) => {
    switch (type) {
      case "agent": return <Bot className="h-5 w-5" />;
      case "database": return <Database className="h-5 w-5" />;
      case "document": return <FileText className="h-5 w-5" />;
      case "api": return <Globe className="h-5 w-5" />;
      default: return <Bot className="h-5 w-5" />;
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold mb-2">Team Resources</h1>
          <p className="text-muted-foreground">
            Manage resources and their relationships to teams.
          </p>
        </div>
        <Button className="flex items-center gap-1">
          <Plus className="h-4 w-4" /> Add Resource
        </Button>
      </div>

      <Card className="p-6">
        <div className="flex flex-col gap-4">
          <div className="flex items-center gap-4">
            <div className="flex-1">
              <Select value={selectedTeam} onValueChange={setSelectedTeam}>
                <SelectTrigger>
                  <SelectValue placeholder="Filter by team" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Teams</SelectItem>
                  {teams.map((team) => (
                    <SelectItem key={team.id} value={team.id}>{team.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex-1 relative">
              <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input placeholder="Search resources..." className="pl-8" />
            </div>
          </div>

          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[250px]">Resource</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Teams</TableHead>
                <TableHead>Access Level</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredResources.map((resource) => (
                <React.Fragment key={resource.id}>
                  <TableRow 
                    className="cursor-pointer"
                    onClick={() => setExpandedResource(
                      expandedResource === resource.id ? null : resource.id
                    )}
                  >
                    <TableCell>
                      <div className="flex items-center gap-2">
                        {getResourceIcon(resource.type)}
                        <div>
                          <div className="font-medium">{resource.name}</div>
                          <div className="text-sm text-muted-foreground">{resource.description}</div>
                        </div>
                      </div>
                    </TableCell>
                    <TableCell className="capitalize">{resource.type}</TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        {resource.teams.map((team, index) => (
                          <Badge key={index} variant="outline" className="bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400 border-blue-200 dark:border-blue-800">
                            {team}
                          </Badge>
                        ))}
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className={accessLevelColors[resource.accessLevel]}>
                        {resource.accessLevel.toUpperCase()}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-2">
                        <Button variant="ghost" size="icon">
                          <Edit className="h-4 w-4" />
                        </Button>
                        {expandedResource === resource.id ? (
                          <ChevronDown className="h-4 w-4" />
                        ) : (
                          <ChevronRight className="h-4 w-4" />
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                  {expandedResource === resource.id && (
                    <TableRow>
                      <TableCell colSpan={5} className="bg-neutral-50 dark:bg-neutral-800/50">
                        <div className="p-4">
                          <h3 className="font-medium mb-2">Access Control Details</h3>
                          <div className="space-y-4">
                            <div>
                              <h4 className="text-sm font-medium mb-1">Team Access</h4>
                              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                                {teams.map((team) => (
                                  <div key={team.id} className="flex items-center justify-between p-2 border rounded-md">
                                    <div className="flex items-center gap-2">
                                      <Users className="h-4 w-4" />
                                      <span>{team.name}</span>
                                    </div>
                                    <Select defaultValue={resource.teams.includes(team.name) ? resource.accessLevel : "none"}>
                                      <SelectTrigger className="w-[100px]">
                                        <SelectValue />
                                      </SelectTrigger>
                                      <SelectContent>
                                        <SelectItem value="none">None</SelectItem>
                                        <SelectItem value="read">Read</SelectItem>
                                        <SelectItem value="write">Write</SelectItem>
                                        <SelectItem value="admin">Admin</SelectItem>
                                      </SelectContent>
                                    </Select>
                                  </div>
                                ))}
                              </div>
                            </div>
                            
                            <div>
                              <h4 className="text-sm font-medium mb-1">Inherited Access</h4>
                              <p className="text-sm text-muted-foreground">
                                Members of these teams will inherit access to this resource based on their team membership.
                              </p>
                            </div>
                            
                            <div className="flex justify-end">
                              <Button size="sm">Save Changes</Button>
                            </div>
                          </div>
                        </div>
                      </TableCell>
                    </TableRow>
                  )}
                </React.Fragment>
              ))}
            </TableBody>
          </Table>
        </div>
      </Card>

      <div>
        <h2 className="text-xl font-semibold mb-4">Resource Access Matrix</h2>
        <Card className="p-6 overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[250px]">Resource</TableHead>
                {teams.map((team) => (
                  <TableHead key={team.id} className="text-center">{team.name}</TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {resources.map((resource) => (
                <TableRow key={resource.id}>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      {getResourceIcon(resource.type)}
                      <span className="font-medium">{resource.name}</span>
                    </div>
                  </TableCell>
                  {teams.map((team) => (
                    <TableCell key={`${resource.id}-${team.id}`} className="text-center">
                      {resource.teams.includes(team.name) ? (
                        <Badge variant="outline" className={accessLevelColors[resource.accessLevel]}>
                          {resource.accessLevel.toUpperCase()}
                        </Badge>
                      ) : (
                        <Badge variant="outline" className={accessLevelColors["none"]}>
                          NONE
                        </Badge>
                      )}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      </div>

      <div>
        <h2 className="text-xl font-semibold mb-4">ReBAC Resource Relationships</h2>
        <Card className="p-6">
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              In Relation-Based Access Control (ReBAC), resources are connected to teams and members through relationships:
            </p>
            
            <ul className="list-disc pl-5 text-sm space-y-2">
              <li>
                <span className="font-medium">Direct Resource Access:</span> Teams can be granted direct access to resources
              </li>
              <li>
                <span className="font-medium">Inherited Resource Access:</span> Members inherit resource access through their team memberships
              </li>
              <li>
                <span className="font-medium">Resource Hierarchy:</span> Resources can have parent-child relationships, creating access inheritance chains
              </li>
              <li>
                <span className="font-medium">Context-Based Access:</span> Access can be determined by the relationship context (e.g., project-specific access)
              </li>
            </ul>
          </div>
        </Card>
      </div>
    </div>
  );
} 