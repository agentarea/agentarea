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
  Mail,
  Calendar,
  Shield,
  Bot
} from "lucide-react";

interface Member {
  id: string;
  name: string;
  email: string;
  role: "Admin" | "Developer" | "Viewer";
  joinedDate: string;
  status: "active" | "invited";
  agentsManaged: number;
}

const members: Member[] = [
  {
    id: "user-1",
    name: "John Doe",
    email: "john.doe@example.com",
    role: "Admin",
    joinedDate: "Jan 15, 2024",
    status: "active",
    agentsManaged: 5
  },
  {
    id: "user-2",
    name: "Jane Smith",
    email: "jane.smith@example.com",
    role: "Developer",
    joinedDate: "Feb 1, 2024",
    status: "active",
    agentsManaged: 3
  },
  {
    id: "user-3",
    name: "Bob Wilson",
    email: "bob.wilson@example.com",
    role: "Viewer",
    joinedDate: "Feb 10, 2024",
    status: "invited",
    agentsManaged: 0
  }
];

const roleColors = {
  Admin: "bg-purple-100 text-purple-700",
  Developer: "bg-blue-100 text-blue-700",
  Viewer: "bg-gray-100 text-gray-700"
};

export default function MembersPage() {
  return (
    <div className="p-8">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-4xl font-bold">Team Members</h1>
          <p className="text-lg text-muted-foreground mt-2">
            Manage your organization's members and their roles
          </p>
        </div>
        <button className="bg-primary text-primary-foreground hover:bg-primary/90 px-4 py-2 rounded-lg flex items-center gap-2">
          <Plus className="h-5 w-5" />
          Invite Member
        </button>
      </div>

      <div className="flex gap-4 mb-6">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-muted-foreground h-4 w-4" />
          <Input
            placeholder="Search members..."
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

      <Card>
        <div className="divide-y">
          {members.map((member) => (
            <div key={member.id} className="p-4 flex items-center justify-between">
              <div className="flex items-center gap-4">
                <div className="h-10 w-10 bg-primary/10 rounded-full flex items-center justify-center">
                  <span className="text-lg font-medium">
                    {member.name.split(" ").map(n => n[0]).join("")}
                  </span>
                </div>
                <div>
                  <div className="flex items-center gap-3">
                    <h3 className="font-medium">{member.name}</h3>
                    <span className={`text-xs px-2 py-1 rounded-full ${roleColors[member.role]}`}>
                      {member.role}
                    </span>
                    {member.status === "invited" && (
                      <span className="text-xs px-2 py-1 rounded-full bg-yellow-100 text-yellow-700">
                        Pending
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-4 mt-1">
                    <div className="flex items-center gap-1 text-sm text-muted-foreground">
                      <Mail className="h-4 w-4" />
                      {member.email}
                    </div>
                    <div className="flex items-center gap-1 text-sm text-muted-foreground">
                      <Calendar className="h-4 w-4" />
                      Joined {member.joinedDate}
                    </div>
                    <div className="flex items-center gap-1 text-sm text-muted-foreground">
                      <Bot className="h-4 w-4" />
                      {member.agentsManaged} agents
                    </div>
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button className="p-2 hover:bg-secondary rounded-lg">
                  <Shield className="h-5 w-5" />
                </button>
                <button className="p-2 hover:bg-secondary rounded-lg">
                  <MoreVertical className="h-5 w-5" />
                </button>
              </div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
} 