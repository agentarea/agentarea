"use client";

import { Card } from "@/components/ui/card";
import {
  ArrowRight,
  Bot,
  Database,
  Shield,
  UserCircle,
  Users
} from "lucide-react";
import Link from "next/link";
import React from "react";

interface EntityRelationship {
  from: {
    type: string;
    name: string;
    icon: React.ReactNode;
  };
  to: {
    type: string;
    name: string;
    icon: React.ReactNode;
  };
  relationship: string;
}

const relationships: EntityRelationship[] = [
  {
    from: { type: "Member", name: "John Doe", icon: <UserCircle className="h-4 w-4" /> },
    to: { type: "Team", name: "Customer Support", icon: <Users className="h-4 w-4" /> },
    relationship: "is member of"
  },
  {
    from: { type: "Team", name: "Customer Support", icon: <Users className="h-4 w-4" /> },
    to: { type: "Resource", name: "Support Agents", icon: <Bot className="h-4 w-4" /> },
    relationship: "has access to"
  },
  {
    from: { type: "Policy", name: "Agent Access Control", icon: <Shield className="h-4 w-4" /> },
    to: { type: "Team", name: "Data Analytics", icon: <Users className="h-4 w-4" /> },
    relationship: "grants permissions to"
  },
  {
    from: { type: "Member", name: "Jane Smith", icon: <UserCircle className="h-4 w-4" /> },
    to: { type: "Resource", name: "Customer Database", icon: <Database className="h-4 w-4" /> },
    relationship: "can manage"
  }
];

export default function OrganizationOverview() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold mb-2">Organization Overview</h1>
        <p className="text-muted-foreground">
          Manage your organization&apos;s structure, members, teams, and access policies.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <Card className="p-4 flex flex-col gap-2">
          <div className="flex items-center gap-2">
            <UserCircle className="h-5 w-5" />
            <h3 className="font-semibold">Members</h3>
          </div>
          <p className="text-sm text-muted-foreground">
            Manage individual users and their roles within your organization.
          </p>
          <Link 
            href="/organization/members" 
            className="text-sm text-blue-600 dark:text-blue-400 flex items-center gap-1 mt-2"
          >
            View Members <ArrowRight className="h-3 w-3" />
          </Link>
        </Card>

        <Card className="p-4 flex flex-col gap-2">
          <div className="flex items-center gap-2">
            <Users className="h-5 w-5" />
            <h3 className="font-semibold">Teams</h3>
          </div>
          <p className="text-sm text-muted-foreground">
            Organize members into teams with specific access permissions.
          </p>
          <Link 
            href="/organization/teams" 
            className="text-sm text-blue-600 dark:text-blue-400 flex items-center gap-1 mt-2"
          >
            View Teams <ArrowRight className="h-3 w-3" />
          </Link>
        </Card>

        <Card className="p-4 flex flex-col gap-2">
          <div className="flex items-center gap-2">
            <Shield className="h-5 w-5" />
            <h3 className="font-semibold">Policies</h3>
          </div>
          <p className="text-sm text-muted-foreground">
            Define access control policies and permissions.
          </p>
          <Link 
            href="/organization/policies" 
            className="text-sm text-blue-600 dark:text-blue-400 flex items-center gap-1 mt-2"
          >
            View Policies <ArrowRight className="h-3 w-3" />
          </Link>
        </Card>
      </div>

      <div>
        <h2 className="text-xl font-semibold mb-4">Relationship Graph</h2>
        <Card className="p-6">
          <div className="flex flex-col gap-4">
            <p className="text-sm text-muted-foreground mb-2">
              This graph shows the relationships between different entities in your organization.
            </p>
            
            {relationships.map((rel, index) => (
              <div key={index} className="flex items-center gap-2 text-sm">
                <div className="flex items-center gap-1 min-w-[150px]">
                  {rel.from.icon}
                  <span className="font-medium">{rel.from.name}</span>
                  <span className="text-xs text-muted-foreground">({rel.from.type})</span>
                </div>
                
                <div className="flex items-center gap-1">
                  <ArrowRight className="h-3 w-3" />
                  <span className="text-xs italic">{rel.relationship}</span>
                  <ArrowRight className="h-3 w-3" />
                </div>
                
                <div className="flex items-center gap-1">
                  {rel.to.icon}
                  <span className="font-medium">{rel.to.name}</span>
                  <span className="text-xs text-muted-foreground">({rel.to.type})</span>
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <div>
        <h2 className="text-xl font-semibold mb-4">ReBAC Implementation</h2>
        <Card className="p-6">
          <div className="space-y-4">
            <p className="text-sm">
              This organization section implements Relation-Based Access Control (ReBAC), which defines permissions based on the relationships between entities.
            </p>
            
            <div className="flex flex-col gap-2">
              <h3 className="font-medium">Key Concepts:</h3>
              <ul className="list-disc pl-5 text-sm space-y-1">
                <li><span className="font-medium">Entities:</span> Members, Teams, Resources, and Policies</li>
                <li><span className="font-medium">Relationships:</span> Connections between entities (e.g., membership, ownership)</li>
                <li><span className="font-medium">Permissions:</span> Access rights derived from relationships</li>
              </ul>
            </div>
            
            <div className="flex flex-col gap-2">
              <h3 className="font-medium">Benefits:</h3>
              <ul className="list-disc pl-5 text-sm space-y-1">
                <li>More flexible than traditional role-based access control</li>
                <li>Permissions automatically propagate through relationships</li>
                <li>Easier to model complex organizational structures</li>
              </ul>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
} 