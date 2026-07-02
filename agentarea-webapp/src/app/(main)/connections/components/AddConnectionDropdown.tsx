"use client";

import { useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { ChevronRight, LayoutGrid, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { OpenAPIConnectionMark } from "./MCPCard";

interface ConnectionOption {
  id: "catalog" | "mcp" | "openapi";
  title: string;
  description: string;
  href: string;
  iconClass: string;
  icon: ReactNode;
}

const OPTIONS: ConnectionOption[] = [
  {
    id: "catalog",
    title: "Browse Catalog",
    description:
      "Connect a ready-made integration (Asana, GitHub, …) from the catalog.",
    href: "/explore?type=mcp_servers",
    iconClass: "bg-primary/5",
    icon: <LayoutGrid className="h-5 w-5 text-primary" />,
  },
  {
    id: "mcp",
    title: "Connect MCP Server",
    description:
      "Create a reusable connection from a Docker image, command, or hosted URL.",
    href: "/connections/add",
    iconClass: "bg-primary/5",
    icon: <img src="/mcp.svg" alt="" className="h-5 w-5 object-contain" />,
  },
  {
    id: "openapi",
    title: "OpenAPI Connection",
    description:
      "Wrap a REST API as agent tools by importing its OpenAPI / Swagger spec.",
    href: "/connections/add-openapi",
    iconClass: "bg-zinc-100 dark:bg-zinc-800",
    icon: <OpenAPIConnectionMark className="h-5 w-5 rounded text-[7px]" />,
  },
];

export function AddConnectionDropdown() {
  const router = useRouter();
  const [open, setOpen] = useState(false);

  const handleSelect = (href: string) => {
    setOpen(false);
    router.push(href);
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          className="shrink-0 gap-2"
          size="xs"
          data-test="new-connection-button"
        >
          <Plus className="mr-1 h-4 w-4" />
          Add Connection
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Add a connection</DialogTitle>
          <DialogDescription>
            Choose how you want to expose tools to your agents.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3 sm:grid-cols-2">
          {OPTIONS.map((option) => {
            return (
              <button
                key={option.id}
                type="button"
                onClick={() => handleSelect(option.href)}
                className={cn(
                  "group flex flex-col items-start gap-3 rounded-lg border border-border bg-card p-4 text-left transition-colors",
                  "hover:border-primary hover:bg-accent focus-visible:border-primary focus-visible:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                )}
                data-test={`new-connection-${option.id}`}
              >
                <div className="flex w-full items-start justify-between">
                  <div
                    className={cn(
                      "flex h-9 w-9 items-center justify-center rounded-md",
                      option.iconClass
                    )}
                  >
                    {option.icon}
                  </div>
                  <ChevronRight className="h-4 w-4 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
                </div>
                <div className="space-y-1">
                  <div className="text-sm font-medium">{option.title}</div>
                  <p className="text-xs text-muted-foreground">
                    {option.description}
                  </p>
                </div>
              </button>
            );
          })}
        </div>
      </DialogContent>
    </Dialog>
  );
}
