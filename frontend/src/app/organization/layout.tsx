"use client";

import React, { useState } from "react";
import { 
  UserCircle, 
  Users, 
  Shield, 
  LineChart, 
  ClipboardList,
  ChevronRight,
  ChevronDown,
  FolderTree
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

interface TreeNode {
  id: string;
  label: string;
  icon: React.ReactNode;
  href: string;
  children?: TreeNode[];
}

const organizationTree: TreeNode[] = [
  {
    id: "overview",
    label: "Overview",
    icon: <FolderTree className="h-4 w-4" />,
    href: "/organization",
  },
  {
    id: "members",
    label: "Members",
    icon: <UserCircle className="h-4 w-4" />,
    href: "/organization/members",
    children: [
      {
        id: "roles",
        label: "Roles",
        icon: <Shield className="h-4 w-4" />,
        href: "/organization/members/roles",
      }
    ]
  },
  {
    id: "teams",
    label: "Teams",
    icon: <Users className="h-4 w-4" />,
    href: "/organization/teams",
    children: [
      {
        id: "team-members",
        label: "Team Members",
        icon: <UserCircle className="h-4 w-4" />,
        href: "/organization/teams/members",
      },
      {
        id: "team-resources",
        label: "Team Resources",
        icon: <FolderTree className="h-4 w-4" />,
        href: "/organization/teams/resources",
      }
    ]
  },
  {
    id: "policies",
    label: "Policies",
    icon: <Shield className="h-4 w-4" />,
    href: "/organization/policies",
    children: [
      {
        id: "access-policies",
        label: "Access Policies",
        icon: <Shield className="h-4 w-4" />,
        href: "/organization/policies/access",
      },
      {
        id: "resource-policies",
        label: "Resource Policies",
        icon: <Shield className="h-4 w-4" />,
        href: "/organization/policies/resources",
      }
    ]
  },
  {
    id: "usage",
    label: "Usage",
    icon: <LineChart className="h-4 w-4" />,
    href: "/organization/usage",
  },
  {
    id: "audit",
    label: "Audit Log",
    icon: <ClipboardList className="h-4 w-4" />,
    href: "/organization/audit",
  }
];

const TreeNodeComponent = ({ node, depth = 0 }: { node: TreeNode; depth?: number }) => {
  const [expanded, setExpanded] = useState(false);
  const pathname = usePathname();
  const isActive = pathname === node.href;
  const hasChildren = node.children && node.children.length > 0;

  return (
    <div className="flex flex-col">
      <Link 
        href={node.href}
        className={cn(
          "flex items-center py-1 px-2 rounded-md text-sm",
          "hover:bg-neutral-200 dark:hover:bg-neutral-700",
          isActive && "bg-neutral-200 dark:bg-neutral-700 font-medium",
          depth > 0 && "ml-4"
        )}
        onClick={(e) => {
          if (hasChildren) {
            e.preventDefault();
            setExpanded(!expanded);
          }
        }}
      >
        <div className="flex items-center gap-2 w-full">
          {node.icon}
          <span>{node.label}</span>
          {hasChildren && (
            <div className="ml-auto">
              {expanded ? (
                <ChevronDown className="h-4 w-4" />
              ) : (
                <ChevronRight className="h-4 w-4" />
              )}
            </div>
          )}
        </div>
      </Link>
      
      {hasChildren && expanded && (
        <div className="mt-1">
          {node.children?.map((child) => (
            <TreeNodeComponent key={child.id} node={child} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
};

export default function OrganizationLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex h-full">
      <div className="w-64 border-r border-neutral-200 dark:border-neutral-700 p-4 h-full">
        <h2 className="font-semibold mb-4">Organization</h2>
        <div className="flex flex-col gap-1">
          {organizationTree.map((node) => (
            <TreeNodeComponent key={node.id} node={node} />
          ))}
        </div>
      </div>
      <div className="flex-1 p-6">
        {children}
      </div>
    </div>
  );
} 