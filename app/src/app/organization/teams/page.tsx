"use client";

import React from "react";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Search,
  Filter,
  ArrowUpDown,
  Plus,
  MoreVertical,
  Users,
  Bot,
  Settings,
  ChevronRight
} from "lucide-react";

interface Team {
  id: string;
  name: string;
  description: string;
  members: number;
  agents: number;
  lead: string;
  created: string;
}

const teams: Team[] = [
  {
    id: "team-1",
    name: "Customer Support",
    description: "Team responsible for customer support automation agents",
    members: 8,
    agents: 5,
    lead: "John Doe",
    created: "Jan 15, 2024"
  },
  {
    id: "team-2",
    name: "Data Analytics",
    description: "Team managing data processing and analytics agents",
    members: 6,
    agents: 4,
    lead: "Jane Smith",
    created: "Feb 1, 2024"
  },
  {
    id: "team-3",
    name: "Integration",
    description: "Team handling system integration and automation",
    members: 4,
    agents: 3,
    lead: "Bob Wilson",
    created: "Feb 10, 2024"
  }
];

export default function TeamsPage() {
  return (
    <div className="p-8">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-4xl font-bold">Teams</h1>
          <p className="text-lg text-muted-foreground mt-2">
            Manage your organization&apos;s teams and their resources
          </p>
        </div>
        <button className="bg-primary text-primary-foreground hover:bg-primary/90 px-4 py-2 rounded-lg flex items-center gap-2">
          <Plus className="h-5 w-5" />
          Create Team
        </button>
      </div>

      <div className="flex gap-4 mb-6">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-muted-foreground h-4 w-4" />
          <Input
            placeholder="Search teams..."
            className="pl-10"
          />
        </div>
        <button className="px-4 py-2 border rounded-lg flex items-center gap-2 hover:bg-secondary">
          <Filter className="h-4 w-4" />
          Filter
        </button>
        <button className="px-4 py-2 border rounded-lg flex items-center gap-2 hover:bg-secondary">
          <ArrowUpDown className="h-4 w-4" />
          Sort
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {teams.map((team) => (
          <Card key={team.id} className="p-6">
            <div className="flex items-start justify-between mb-4">
              <div className="flex items-center gap-3">
                <div className="h-12 w-12 bg-primary/10 rounded-lg flex items-center justify-center">
                  <Users className="h-6 w-6 text-primary" />
                </div>
                <div>
                  <h3 className="font-semibold">{team.name}</h3>
                  <span className="text-sm text-muted-foreground">Led by {team.lead}</span>
                </div>
              </div>
              <button className="p-2 hover:bg-secondary rounded-lg">
                <MoreVertical className="h-5 w-5" />
              </button>
            </div>
            
            <p className="text-sm text-muted-foreground mb-6">{team.description}</p>

            <div className="grid grid-cols-2 gap-4 mb-6">
              <div className="bg-secondary/20 p-3 rounded-lg">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <Users className="h-4 w-4" />
                  Members
                </div>
                <p className="text-2xl font-bold mt-1">{team.members}</p>
              </div>
              <div className="bg-secondary/20 p-3 rounded-lg">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <Bot className="h-4 w-4" />
                  Agents
                </div>
                <p className="text-2xl font-bold mt-1">{team.agents}</p>
              </div>
            </div>

            <div className="flex justify-between items-center text-sm">
              <span className="text-muted-foreground">Created {team.created}</span>
              <div className="flex gap-2">
                <button className="p-2 hover:bg-secondary rounded-lg" title="Team Settings">
                  <Settings className="h-4 w-4" />
                </button>
                <button className="p-2 hover:bg-secondary rounded-lg" title="View Details">
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
} 