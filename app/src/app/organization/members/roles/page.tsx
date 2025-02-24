"use client";

import React from "react";
import { Card } from "@/components/ui/card";
import { 
  Shield, 
  Check, 
  X,
  Edit,
  Plus,
  Trash2
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

interface Role {
  id: string;
  name: string;
  description: string;
  permissions: {
    [key: string]: boolean;
  };
  isDefault: boolean;
}

const roles: Role[] = [
  {
    id: "role-1",
    name: "Admin",
    description: "Full access to all resources and settings",
    permissions: {
      "Create Agents": true,
      "Edit Agents": true,
      "Delete Agents": true,
      "Manage Teams": true,
      "Manage Members": true,
      "Manage Policies": true,
      "View Usage": true,
      "View Audit Log": true,
    },
    isDefault: false
  },
  {
    id: "role-2",
    name: "Developer",
    description: "Can create and manage agents, but cannot manage organization settings",
    permissions: {
      "Create Agents": true,
      "Edit Agents": true,
      "Delete Agents": true,
      "Manage Teams": false,
      "Manage Members": false,
      "Manage Policies": false,
      "View Usage": true,
      "View Audit Log": false,
    },
    isDefault: true
  },
  {
    id: "role-3",
    name: "Viewer",
    description: "Read-only access to agents and resources",
    permissions: {
      "Create Agents": false,
      "Edit Agents": false,
      "Delete Agents": false,
      "Manage Teams": false,
      "Manage Members": false,
      "Manage Policies": false,
      "View Usage": true,
      "View Audit Log": false,
    },
    isDefault: false
  }
];

export default function MemberRolesPage() {
  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold mb-2">Member Roles</h1>
          <p className="text-muted-foreground">
            Define roles and permissions for organization members.
          </p>
        </div>
        <Button className="flex items-center gap-1">
          <Plus className="h-4 w-4" /> Create Role
        </Button>
      </div>

      <Card>
        <div className="p-6">
          <p className="text-sm text-muted-foreground mb-4">
            Roles define what actions members can perform within the organization. 
            Each member can be assigned one or more roles.
          </p>

          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[200px]">Role</TableHead>
                <TableHead>Description</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {roles.map((role) => (
                <TableRow key={role.id}>
                  <TableCell className="font-medium">{role.name}</TableCell>
                  <TableCell>{role.description}</TableCell>
                  <TableCell>
                    {role.isDefault && (
                      <Badge variant="outline" className="bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400 border-blue-200 dark:border-blue-800">
                        Default
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-2">
                      <Button variant="ghost" size="icon">
                        <Edit className="h-4 w-4" />
                      </Button>
                      <Button variant="ghost" size="icon">
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </Card>

      <div>
        <h2 className="text-xl font-semibold mb-4">Permission Matrix</h2>
        <Card>
          <div className="p-6 overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[200px]">Permission</TableHead>
                  {roles.map((role) => (
                    <TableHead key={role.id} className="text-center">{role.name}</TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {Object.keys(roles[0].permissions).map((permission) => (
                  <TableRow key={permission}>
                    <TableCell className="font-medium">{permission}</TableCell>
                    {roles.map((role) => (
                      <TableCell key={`${role.id}-${permission}`} className="text-center">
                        {role.permissions[permission] ? (
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
          </div>
        </Card>
      </div>

      <div>
        <h2 className="text-xl font-semibold mb-4">Role Inheritance</h2>
        <Card className="p-6">
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              In ReBAC, permissions can be inherited through relationships. For example, a member inherits permissions from their roles and teams.
            </p>
            
            <div className="flex flex-col gap-4 mt-4">
              <div className="flex items-center gap-2 p-3 border rounded-md">
                <Shield className="h-5 w-5 text-blue-600" />
                <div>
                  <h3 className="font-medium">Direct Permissions</h3>
                  <p className="text-xs text-muted-foreground">Permissions explicitly granted to a role</p>
                </div>
              </div>
              
              <div className="flex items-center gap-2 p-3 border rounded-md">
                <Shield className="h-5 w-5 text-green-600" />
                <div>
                  <h3 className="font-medium">Inherited Permissions</h3>
                  <p className="text-xs text-muted-foreground">Permissions inherited through relationships (e.g., team membership)</p>
                </div>
              </div>
              
              <div className="flex items-center gap-2 p-3 border rounded-md">
                <Shield className="h-5 w-5 text-red-600" />
                <div>
                  <h3 className="font-medium">Denied Permissions</h3>
                  <p className="text-xs text-muted-foreground">Permissions explicitly denied, overriding inherited permissions</p>
                </div>
              </div>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
} 