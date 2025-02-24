"use client";

import React from "react";
import { 
  ShoppingCart, 
  Package, 
  Database, 
  Bot, 
  Cpu, 
  Wrench, 
  Bookmark
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

interface NavItem {
  id: string;
  label: string;
  icon: React.ReactNode;
  href: string;
}

const primaryNavItems: NavItem[] = [
  {
    id: "browse",
    label: "Browse All",
    icon: <ShoppingCart className="h-4 w-4" />,
    href: "/marketplace/browse",
  },
  {
    id: "subscriptions",
    label: "My Subscriptions",
    icon: <Bookmark className="h-4 w-4" />,
    href: "/marketplace/subscriptions",
  },
  {
    id: "tools",
    label: "Tools",
    icon: <Wrench className="h-4 w-4" />,
    href: "/marketplace/tools",
  },
  {
    id: "sources",
    label: "Data Sources",
    icon: <Database className="h-4 w-4" />,
    href: "/marketplace/sources",
  },
  {
    id: "llms",
    label: "LLM Models",
    icon: <Cpu className="h-4 w-4" />,
    href: "/marketplace/llms",
  },
  {
    id: "agents",
    label: "Agents",
    icon: <Bot className="h-4 w-4" />,
    href: "/marketplace/agents",
  }
];

const secondaryNavItems: Record<string, NavItem[]> = {
  tools: [
    {
      id: "tools-browse",
      label: "Browse Tools",
      icon: <ShoppingCart className="h-4 w-4" />,
      href: "/marketplace/tools/browse",
    },
    {
      id: "tools-create",
      label: "Create Tool Spec",
      icon: <Package className="h-4 w-4" />,
      href: "/marketplace/tools/create",
    }
  ],
  sources: [
    {
      id: "sources-browse",
      label: "Browse Sources",
      icon: <ShoppingCart className="h-4 w-4" />,
      href: "/marketplace/sources/browse",
    },
    {
      id: "sources-create",
      label: "Create Source Spec",
      icon: <Package className="h-4 w-4" />,
      href: "/marketplace/sources/create",
    }
  ],
  llms: [
    {
      id: "llms-browse",
      label: "Browse LLMs",
      icon: <ShoppingCart className="h-4 w-4" />,
      href: "/marketplace/llms/browse",
    },
    {
      id: "llms-create",
      label: "Create LLM Spec",
      icon: <Package className="h-4 w-4" />,
      href: "/marketplace/llms/create",
    }
  ],
  agents: [
    {
      id: "agents-browse",
      label: "Browse Agents",
      icon: <ShoppingCart className="h-4 w-4" />,
      href: "/marketplace/agents/browse",
    },
    {
      id: "agents-create",
      label: "Create Agent Spec",
      icon: <Package className="h-4 w-4" />,
      href: "/marketplace/agents/create",
    },
    {
      id: "agents-mcp",
      label: "MCP Compatible",
      icon: <Bot className="h-4 w-4" />,
      href: "/marketplace/agents/mcp",
    }
  ]
};

export default function MarketplaceLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  
  // Determine the active primary section
  const activePrimarySection = primaryNavItems.find(
    item => pathname === item.href || pathname.startsWith(`${item.href}/`)
  )?.id || "";
  
  // Get secondary nav items for the active section
  const activeSecondaryItems = secondaryNavItems[activePrimarySection] || [];
  
  return (
    <div className="flex flex-col h-full">
      <div className="border-b border-neutral-200 dark:border-neutral-700 p-4">
        <h1 className="text-2xl font-bold mb-4">Marketplace</h1>
        
        <Tabs 
          value={activePrimarySection} 
          className="w-full"
          onValueChange={(value) => {
            const item = primaryNavItems.find(item => item.id === value);
            if (item) {
              window.location.href = item.href;
            }
          }}
        >
          <TabsList className="w-full justify-start">
            {primaryNavItems.map((item) => (
              <TabsTrigger 
                key={item.id} 
                value={item.id}
                className="flex items-center gap-2"
              >
                {item.icon}
                {item.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        
        {activeSecondaryItems.length > 0 && (
          <div className="flex mt-4 gap-2">
            {activeSecondaryItems.map((item) => (
              <Link 
                key={item.id}
                href={item.href}
                className={cn(
                  "flex items-center gap-2 px-3 py-1.5 rounded-md text-sm",
                  "hover:bg-neutral-100 dark:hover:bg-neutral-800",
                  pathname === item.href && "bg-neutral-100 dark:bg-neutral-800 font-medium"
                )}
              >
                {item.icon}
                {item.label}
              </Link>
            ))}
          </div>
        )}
      </div>
      
      <div className="flex-1 p-6 overflow-auto">
        {children}
      </div>
    </div>
  );
} 