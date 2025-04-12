"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Check,
  Plus,
  Search,
  UserCircle,
  X
} from "lucide-react";
import { useState } from "react";

interface Team {
  id: string;
  name: string;
  description: string;
  members: number;
}

interface TeamMember {
  id: string;
  name: string;
  email: string;
  role: string;
  teams: string[];
  joinedDate: string;
}

const teams: Team[] = [
  {
    id: "team-1",
    name: "Customer Support",
    description: "Team responsible for customer support automation agents",
    members: 8,
  },
  {
    id: "team-2",
    name: "Data Analytics",
    description: "Team managing data processing and analytics agents",
    members: 6,
  },
  {
    id: "team-3",
    name: "Integration",
    description: "Team handling system integration and automation",
    members: 5,
  },
];

const members: TeamMember[] = [
  {
    id: "user-1",
    name: "John Doe",
    email: "john.doe@example.com",
    role: "Team Lead",
    teams: ["Customer Support", "Integration"],
    joinedDate: "Jan 15, 2024",
  },
  {
    id: "user-2",
    name: "Jane Smith",
    email: "jane.smith@example.com",
    role: "Developer",
    teams: ["Data Analytics"],
    joinedDate: "Feb 1, 2024",
  },
  {
    id: "user-3",
    name: "Bob Wilson",
    email: "bob.wilson@example.com",
    role: "Developer",
    teams: ["Customer Support", "Data Analytics"],
    joinedDate: "Jan 20, 2024",
  },
  {
    id: "user-4",
    name: "Alice Johnson",
    email: "alice.johnson@example.com",
    role: "Team Lead",
    teams: ["Data Analytics"],
    joinedDate: "Dec 10, 2023",
  },
  {
    id: "user-5",
    name: "Charlie Brown",
    email: "charlie.brown@example.com",
    role: "Developer",
    teams: ["Integration"],
    joinedDate: "Feb 15, 2024",
  },
];

export default function TeamMembersPage() {
  const [selectedTeam, setSelectedTeam] = useState<string>("all");
  
  const filteredMembers = selectedTeam === "all" 
    ? members 
    : members.filter(member => member.teams.includes(
        teams.find(team => team.id === selectedTeam)?.name || ""
      ));

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold mb-2">Team Members</h1>
          <p className="text-muted-foreground">
            Manage team memberships and relationships.
          </p>
        </div>
        <Button className="flex items-center gap-1">
          <Plus className="h-4 w-4" /> Add Member to Team
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
              <Input placeholder="Search members..." className="pl-8" />
            </div>
          </div>

          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[250px]">Member</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Teams</TableHead>
                <TableHead>Joined</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredMembers.map((member) => (
                <TableRow key={member.id}>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <UserCircle className="h-8 w-8 text-muted-foreground" />
                      <div>
                        <div className="font-medium">{member.name}</div>
                        <div className="text-sm text-muted-foreground">{member.email}</div>
                      </div>
                    </div>
                  </TableCell>
                  <TableCell>{member.role}</TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {member.teams.map((team, index) => (
                        <Badge key={index} variant="outline" className="bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400 border-blue-200 dark:border-blue-800">
                          {team}
                        </Badge>
                      ))}
                    </div>
                  </TableCell>
                  <TableCell>{member.joinedDate}</TableCell>
                  <TableCell className="text-right">
                    <Button variant="ghost" size="sm">Manage Teams</Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </Card>

      <div>
        <h2 className="text-xl font-semibold mb-4">Team Membership Matrix</h2>
        <Card className="p-6 overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[250px]">Member</TableHead>
                {teams.map((team) => (
                  <TableHead key={team.id} className="text-center">{team.name}</TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {members.map((member) => (
                <TableRow key={member.id}>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <UserCircle className="h-5 w-5 text-muted-foreground" />
                      <span className="font-medium">{member.name}</span>
                    </div>
                  </TableCell>
                  {teams.map((team) => (
                    <TableCell key={`${member.id}-${team.id}`} className="text-center">
                      {member.teams.includes(team.name) ? (
                        <Check className="h-4 w-4 text-green-600 mx-auto" />
                      ) : (
                        <X className="h-4 w-4 text-red-600 mx-auto" />
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
        <h2 className="text-xl font-semibold mb-4">ReBAC Implications</h2>
        <Card className="p-6">
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              In Relation-Based Access Control (ReBAC), team membership is a key relationship that determines access permissions:
            </p>
            
            <ul className="list-disc pl-5 text-sm space-y-2">
              <li>
                <span className="font-medium">Permission Inheritance:</span> Members inherit permissions from the teams they belong to
              </li>
              <li>
                <span className="font-medium">Multiple Team Memberships:</span> When a user belongs to multiple teams, they receive the combined permissions of all teams
              </li>
              <li>
                <span className="font-medium">Team Hierarchy:</span> Teams can have parent-child relationships, creating permission inheritance chains
              </li>
              <li>
                <span className="font-medium">Context-Aware Access:</span> Permissions can be evaluated based on the relationship context (e.g., a user's role within a team)
              </li>
            </ul>
          </div>
        </Card>
      </div>
    </div>
  );
} 