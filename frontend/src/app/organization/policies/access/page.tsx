"use client";

import React, { useState } from "react";
import { Card } from "@/components/ui/card";
import { 
  Shield, 
  UserCircle, 
  Users, 
  Bot, 
  Database,
  FileText,
  Globe,
  Plus,
  Edit,
  Trash2,
  ChevronRight,
  ChevronDown,
  ArrowRight
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface AccessPolicy {
  id: string;
  name: string;
  description: string;
  subject: {
    type: "member" | "team" | "role";
    name: string;
  };
  resource: {
    type: "agent" | "database" | "document" | "api";
    name: string;
  };
  action: "read" | "write" | "admin";
  condition?: string;
  priority: "high" | "medium" | "low";
}

const accessPolicies: AccessPolicy[] = [
  {
    id: "policy-1",
    name: "Admin Team Full Access",
    description: "Grants admin access to all resources for the Admin team",
    subject: {
      type: "team",
      name: "Admin"
    },
    resource: {
      type: "agent",
      name: "All Agents"
    },
    action: "admin",
    priority: "high"
  },
  {
    id: "policy-2",
    name: "Support Team Agent Access",
    description: "Grants write access to support agents for the Customer Support team",
    subject: {
      type: "team",
      name: "Customer Support"
    },
    resource: {
      type: "agent",
      name: "Customer Support Agent"
    },
    action: "write",
    condition: "Only during business hours",
    priority: "medium"
  },
  {
    id: "policy-3",
    name: "Analytics Team Database Access",
    description: "Grants read access to customer database for the Data Analytics team",
    subject: {
      type: "team",
      name: "Data Analytics"
    },
    resource: {
      type: "database",
      name: "Customer Database"
    },
    action: "read",
    priority: "medium"
  },
  {
    id: "policy-4",
    name: "Developer Role API Access",
    description: "Grants write access to APIs for users with Developer role",
    subject: {
      type: "role",
      name: "Developer"
    },
    resource: {
      type: "api",
      name: "Integration API"
    },
    action: "write",
    priority: "medium"
  },
  {
    id: "policy-5",
    name: "John Doe Admin Access",
    description: "Grants admin access to specific user",
    subject: {
      type: "member",
      name: "John Doe"
    },
    resource: {
      type: "document",
      name: "Documentation Repository"
    },
    action: "admin",
    priority: "low"
  }
];

const priorityColors: Record<string, string> = {
  "high": "bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-400 border-red-200 dark:border-red-800",
  "medium": "bg-yellow-50 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400 border-yellow-200 dark:border-yellow-800",
  "low": "bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400 border-blue-200 dark:border-blue-800"
};

const actionColors: Record<string, string> = {
  "read": "bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400 border-blue-200 dark:border-blue-800",
  "write": "bg-green-50 text-green-700 dark:bg-green-900/30 dark:text-green-400 border-green-200 dark:border-green-800",
  "admin": "bg-purple-50 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400 border-purple-200 dark:border-purple-800"
};

export default function AccessPoliciesPage() {
  const [expandedPolicy, setExpandedPolicy] = useState<string | null>(null);

  const getSubjectIcon = (type: string) => {
    switch (type) {
      case "member": return <UserCircle className="h-5 w-5" />;
      case "team": return <Users className="h-5 w-5" />;
      case "role": return <Shield className="h-5 w-5" />;
      default: return <UserCircle className="h-5 w-5" />;
    }
  };

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
          <h1 className="text-2xl font-bold mb-2">Access Policies</h1>
          <p className="text-muted-foreground">
            Define and manage access control policies for your organization.
          </p>
        </div>
        <Button className="flex items-center gap-1">
          <Plus className="h-4 w-4" /> Create Policy
        </Button>
      </div>

      <Card className="p-6">
        <div className="flex flex-col gap-4">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[250px]">Policy</TableHead>
                <TableHead>Subject</TableHead>
                <TableHead>Resource</TableHead>
                <TableHead>Action</TableHead>
                <TableHead>Priority</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {accessPolicies.map((policy) => (
                <React.Fragment key={policy.id}>
                  <TableRow 
                    className="cursor-pointer"
                    onClick={() => setExpandedPolicy(
                      expandedPolicy === policy.id ? null : policy.id
                    )}
                  >
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <Shield className="h-5 w-5" />
                        <div>
                          <div className="font-medium">{policy.name}</div>
                          <div className="text-sm text-muted-foreground">{policy.description}</div>
                        </div>
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1">
                        {getSubjectIcon(policy.subject.type)}
                        <span>{policy.subject.name}</span>
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1">
                        {getResourceIcon(policy.resource.type)}
                        <span>{policy.resource.name}</span>
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className={actionColors[policy.action]}>
                        {policy.action.toUpperCase()}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className={priorityColors[policy.priority]}>
                        {policy.priority.toUpperCase()}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-2">
                        <Button variant="ghost" size="icon">
                          <Edit className="h-4 w-4" />
                        </Button>
                        {expandedPolicy === policy.id ? (
                          <ChevronDown className="h-4 w-4" />
                        ) : (
                          <ChevronRight className="h-4 w-4" />
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                  {expandedPolicy === policy.id && (
                    <TableRow>
                      <TableCell colSpan={6} className="bg-neutral-50 dark:bg-neutral-800/50">
                        <div className="p-4">
                          <h3 className="font-medium mb-4">Policy Details</h3>
                          <div className="space-y-4">
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                              <div className="space-y-2">
                                <h4 className="text-sm font-medium">Subject Configuration</h4>
                                <div className="p-3 border rounded-md">
                                  <div className="flex items-center gap-2 mb-2">
                                    {getSubjectIcon(policy.subject.type)}
                                    <span className="font-medium">{policy.subject.name}</span>
                                    <span className="text-xs text-muted-foreground capitalize">({policy.subject.type})</span>
                                  </div>
                                  <div className="flex items-center gap-2 mt-3">
                                    <span className="text-sm">Subject Type:</span>
                                    <Select defaultValue={policy.subject.type}>
                                      <SelectTrigger className="w-[150px]">
                                        <SelectValue />
                                      </SelectTrigger>
                                      <SelectContent>
                                        <SelectItem value="member">Member</SelectItem>
                                        <SelectItem value="team">Team</SelectItem>
                                        <SelectItem value="role">Role</SelectItem>
                                      </SelectContent>
                                    </Select>
                                  </div>
                                </div>
                              </div>
                              
                              <div className="space-y-2">
                                <h4 className="text-sm font-medium">Resource Configuration</h4>
                                <div className="p-3 border rounded-md">
                                  <div className="flex items-center gap-2 mb-2">
                                    {getResourceIcon(policy.resource.type)}
                                    <span className="font-medium">{policy.resource.name}</span>
                                    <span className="text-xs text-muted-foreground capitalize">({policy.resource.type})</span>
                                  </div>
                                  <div className="flex items-center gap-2 mt-3">
                                    <span className="text-sm">Resource Type:</span>
                                    <Select defaultValue={policy.resource.type}>
                                      <SelectTrigger className="w-[150px]">
                                        <SelectValue />
                                      </SelectTrigger>
                                      <SelectContent>
                                        <SelectItem value="agent">Agent</SelectItem>
                                        <SelectItem value="database">Database</SelectItem>
                                        <SelectItem value="document">Document</SelectItem>
                                        <SelectItem value="api">API</SelectItem>
                                      </SelectContent>
                                    </Select>
                                  </div>
                                </div>
                              </div>
                            </div>
                            
                            <div className="space-y-2">
                              <h4 className="text-sm font-medium">Access Configuration</h4>
                              <div className="p-3 border rounded-md">
                                <div className="flex items-center gap-2 mb-2">
                                  <div className="flex items-center gap-2">
                                    <span className="text-sm">Action:</span>
                                    <Select defaultValue={policy.action}>
                                      <SelectTrigger className="w-[150px]">
                                        <SelectValue />
                                      </SelectTrigger>
                                      <SelectContent>
                                        <SelectItem value="read">Read</SelectItem>
                                        <SelectItem value="write">Write</SelectItem>
                                        <SelectItem value="admin">Admin</SelectItem>
                                      </SelectContent>
                                    </Select>
                                  </div>
                                  
                                  <div className="flex items-center gap-2 ml-4">
                                    <span className="text-sm">Priority:</span>
                                    <Select defaultValue={policy.priority}>
                                      <SelectTrigger className="w-[150px]">
                                        <SelectValue />
                                      </SelectTrigger>
                                      <SelectContent>
                                        <SelectItem value="high">High</SelectItem>
                                        <SelectItem value="medium">Medium</SelectItem>
                                        <SelectItem value="low">Low</SelectItem>
                                      </SelectContent>
                                    </Select>
                                  </div>
                                </div>
                                
                                {policy.condition && (
                                  <div className="mt-3 p-2 bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-md">
                                    <span className="text-sm font-medium">Condition: </span>
                                    <span className="text-sm">{policy.condition}</span>
                                  </div>
                                )}
                              </div>
                            </div>
                            
                            <div className="flex justify-end gap-2">
                              <Button variant="outline">Cancel</Button>
                              <Button>Save Changes</Button>
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
        <h2 className="text-xl font-semibold mb-4">ReBAC Policy Relationships</h2>
        <Card className="p-6">
          <div className="space-y-6">
            <p className="text-sm text-muted-foreground">
              In Relation-Based Access Control (ReBAC), policies define the relationships between subjects (who), resources (what), and actions (how).
            </p>
            
            <div className="space-y-4">
              <h3 className="font-medium">Policy Components</h3>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div className="p-4 border rounded-md">
                  <div className="flex items-center gap-2 mb-2">
                    <UserCircle className="h-5 w-5 text-blue-600" />
                    <h4 className="font-medium">Subject</h4>
                  </div>
                  <p className="text-sm text-muted-foreground">
                    Who is granted access (Member, Team, Role)
                  </p>
                </div>
                
                <div className="p-4 border rounded-md">
                  <div className="flex items-center gap-2 mb-2">
                    <Database className="h-5 w-5 text-green-600" />
                    <h4 className="font-medium">Resource</h4>
                  </div>
                  <p className="text-sm text-muted-foreground">
                    What is being accessed (Agent, Database, Document, API)
                  </p>
                </div>
                
                <div className="p-4 border rounded-md">
                  <div className="flex items-center gap-2 mb-2">
                    <Shield className="h-5 w-5 text-purple-600" />
                    <h4 className="font-medium">Action</h4>
                  </div>
                  <p className="text-sm text-muted-foreground">
                    How the resource can be accessed (Read, Write, Admin)
                  </p>
                </div>
              </div>
            </div>
            
            <div className="space-y-4">
              <h3 className="font-medium">Policy Evaluation Flow</h3>
              <div className="flex flex-col md:flex-row items-center justify-between gap-4">
                <div className="p-3 border rounded-md flex items-center gap-2">
                  <UserCircle className="h-5 w-5 text-blue-600" />
                  <span>Subject</span>
                </div>
                <ArrowRight className="h-4 w-4 rotate-90 md:rotate-0" />
                <div className="p-3 border rounded-md flex items-center gap-2">
                  <Shield className="h-5 w-5 text-purple-600" />
                  <span>Policy</span>
                </div>
                <ArrowRight className="h-4 w-4 rotate-90 md:rotate-0" />
                <div className="p-3 border rounded-md flex items-center gap-2">
                  <Database className="h-5 w-5 text-green-600" />
                  <span>Resource</span>
                </div>
              </div>
              <p className="text-sm text-muted-foreground">
                When a subject attempts to access a resource, all applicable policies are evaluated to determine if access should be granted.
              </p>
            </div>
            
            <div className="space-y-2">
              <h3 className="font-medium">Advanced ReBAC Features</h3>
              <ul className="list-disc pl-5 text-sm space-y-2">
                <li>
                  <span className="font-medium">Policy Inheritance:</span> Policies can be inherited through relationships
                </li>
                <li>
                  <span className="font-medium">Policy Conflict Resolution:</span> When multiple policies apply, priority determines which takes precedence
                </li>
                <li>
                  <span className="font-medium">Conditional Policies:</span> Access can be granted based on conditions (time, location, etc.)
                </li>
                <li>
                  <span className="font-medium">Relationship-Based Policies:</span> Policies can be defined based on the relationship between entities
                </li>
              </ul>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
} 