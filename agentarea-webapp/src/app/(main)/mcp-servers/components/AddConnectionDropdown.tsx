"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Plus, Server, FileJson2, ChevronRight } from "lucide-react";
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

interface ConnectionOption {
  id: "mcp" | "openapi";
  title: string;
  description: string;
  icon: typeof Server;
  href: string;
  iconClass: string;
}

const OPTIONS: ConnectionOption[] = [
  {
    id: "mcp",
    title: "Connect MCP Server",
    description:
      "Create a reusable connection from a Docker image, command, or hosted URL.",
    icon: Server,
    href: "/mcp-servers/add",
    iconClass: "bg-blue-50 text-blue-600",
  },
  {
    id: "openapi",
    title: "OpenAPI Connection",
    description:
      "Wrap a REST API as agent tools by importing its OpenAPI / Swagger spec.",
    icon: FileJson2,
    href: "/mcp-servers/add-openapi",
    iconClass: "bg-orange-50 text-orange-600",
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
            const Icon = option.icon;
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
                    <Icon className="h-5 w-5" />
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
