"use client";

import React from "react";
import { Card } from "@/components/ui/card";
import {
  Shield,
  Lock,
  Users,
  Database,
  Globe,
  Clock,
  AlertTriangle,
  Plus,
  Edit,
  MoreVertical,
  ChevronRight
} from "lucide-react";

interface Policy {
  id: string;
  name: string;
  description: string;
  type: "security" | "access" | "compliance" | "resource";
  scope: string;
  lastUpdated: string;
  status: "active" | "draft";
  priority: "high" | "medium" | "low";
}

const policies: Policy[] = [
  {
    id: "policy-1",
    name: "Agent Access Control",
    description: "Defines which teams and roles can deploy and manage agents",
    type: "access",
    scope: "All Teams",
    lastUpdated: "2 days ago",
    status: "active",
    priority: "high"
  },
  {
    id: "policy-2",
    name: "Data Source Security",
    description: "Security requirements for connecting external data sources",
    type: "security",
    scope: "Data Sources",
    lastUpdated: "1 week ago",
    status: "active",
    priority: "high"
  },
  {
    id: "policy-3",
    name: "Resource Usage Limits",
    description: "Defines resource quotas and usage limits for agents",
    type: "resource",
    scope: "All Agents",
    lastUpdated: "3 days ago",
    status: "active",
    priority: "medium"
  },
  {
    id: "policy-4",
    name: "Compliance Requirements",
    description: "GDPR and data privacy compliance guidelines",
    type: "compliance",
    scope: "Organization",
    lastUpdated: "5 days ago",
    status: "draft",
    priority: "high"
  }
];

const typeIcons = {
  security: <Lock className="h-6 w-6" />,
  access: <Users className="h-6 w-6" />,
  compliance: <Shield className="h-6 w-6" />,
  resource: <Database className="h-6 w-6" />
};

const priorityColors = {
  high: "bg-red-100 text-red-700",
  medium: "bg-yellow-100 text-yellow-700",
  low: "bg-green-100 text-green-700"
};

const statusColors = {
  active: "bg-green-100 text-green-700",
  draft: "bg-gray-100 text-gray-700"
};

export default function PoliciesPage() {
  return (
    <div className="p-8">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-4xl font-bold">Policies</h1>
          <p className="text-lg text-muted-foreground mt-2">
            Manage organization-wide policies and compliance
          </p>
        </div>
        <button className="bg-primary text-primary-foreground hover:bg-primary/90 px-4 py-2 rounded-lg flex items-center gap-2">
          <Plus className="h-5 w-5" />
          Create Policy
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
        <Card className="p-6">
          <div className="flex items-center gap-2 mb-2">
            <Shield className="h-5 w-5 text-primary" />
            <h3 className="font-medium">Total Policies</h3>
          </div>
          <p className="text-2xl font-bold">12</p>
        </Card>
        <Card className="p-6">
          <div className="flex items-center gap-2 mb-2">
            <AlertTriangle className="h-5 w-5 text-yellow-500" />
            <h3 className="font-medium">High Priority</h3>
          </div>
          <p className="text-2xl font-bold">3</p>
        </Card>
        <Card className="p-6">
          <div className="flex items-center gap-2 mb-2">
            <Clock className="h-5 w-5 text-blue-500" />
            <h3 className="font-medium">Under Review</h3>
          </div>
          <p className="text-2xl font-bold">2</p>
        </Card>
        <Card className="p-6">
          <div className="flex items-center gap-2 mb-2">
            <Globe className="h-5 w-5 text-green-500" />
            <h3 className="font-medium">Global Scope</h3>
          </div>
          <p className="text-2xl font-bold">5</p>
        </Card>
      </div>

      <div className="space-y-6">
        {policies.map((policy) => (
          <Card key={policy.id} className="p-6">
            <div className="flex items-start justify-between">
              <div className="flex items-start gap-4">
                <div className="h-12 w-12 bg-primary/10 rounded-lg flex items-center justify-center">
                  {typeIcons[policy.type]}
                </div>
                <div>
                  <div className="flex items-center gap-3">
                    <h3 className="font-semibold text-lg">{policy.name}</h3>
                    <span className={`text-xs px-2 py-1 rounded-full ${statusColors[policy.status]}`}>
                      {policy.status.charAt(0).toUpperCase() + policy.status.slice(1)}
                    </span>
                    <span className={`text-xs px-2 py-1 rounded-full ${priorityColors[policy.priority]}`}>
                      {policy.priority.charAt(0).toUpperCase() + policy.priority.slice(1)} Priority
                    </span>
                  </div>
                  <p className="text-sm text-muted-foreground mt-1">{policy.description}</p>
                  <div className="flex items-center gap-4 mt-4">
                    <div className="flex items-center gap-1 text-sm text-muted-foreground">
                      <Globe className="h-4 w-4" />
                      Scope: {policy.scope}
                    </div>
                    <div className="flex items-center gap-1 text-sm text-muted-foreground">
                      <Clock className="h-4 w-4" />
                      Updated {policy.lastUpdated}
                    </div>
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button className="p-2 hover:bg-secondary rounded-lg" title="Edit Policy">
                  <Edit className="h-5 w-5" />
                </button>
                <button className="p-2 hover:bg-secondary rounded-lg" title="More Options">
                  <MoreVertical className="h-5 w-5" />
                </button>
                <button className="p-2 hover:bg-secondary rounded-lg" title="View Details">
                  <ChevronRight className="h-5 w-5" />
                </button>
              </div>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
} 