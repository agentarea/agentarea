"use client";

import { KeyRound, Lock, Plus } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

type Backend = {
  id: string;
  name: string;
  description: string;
  icon: typeof KeyRound;
};

const BACKENDS: Backend[] = [
  {
    id: "infisical",
    name: "Infisical",
    description:
      "Sync secrets from your Infisical project and reference them across MCP connections.",
    icon: KeyRound,
  },
  {
    id: "vault",
    name: "HashiCorp Vault",
    description:
      "Read secrets from a Vault backend instead of storing credentials in AgentArea.",
    icon: Lock,
  },
];

export function ExternalBackends() {
  const [active, setActive] = useState<Backend | "request" | null>(null);

  const open = active !== null;
  const isRequest = active === "request";

  return (
    <div className="space-y-3">
      <div>
        <h2 className="text-sm font-medium">External secret backends</h2>
        <p className="text-sm text-muted-foreground">
          Connect a managed secret store instead of keeping credentials per
          connection.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {BACKENDS.map((backend) => {
          const Icon = backend.icon;
          return (
            <button
              key={backend.id}
              type="button"
              onClick={() => setActive(backend)}
              className={cn(
                "group flex items-start gap-3 rounded-lg border border-border/60 p-4 text-left transition-colors",
                "hover:border-border hover:bg-muted/40 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              )}
            >
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
                <Icon className="h-4 w-4" />
              </span>
              <span className="min-w-0 space-y-1">
                <span className="flex items-center gap-2">
                  <span className="text-sm font-medium">{backend.name}</span>
                  <Badge variant="light" size="sm">
                    Coming soon
                  </Badge>
                </span>
                <span className="block text-xs text-muted-foreground">
                  {backend.description}
                </span>
              </span>
            </button>
          );
        })}

        <button
          type="button"
          onClick={() => setActive("request")}
          className={cn(
            "flex items-center gap-3 rounded-lg border border-dashed border-border/60 p-4 text-left transition-colors",
            "hover:border-border hover:bg-muted/40 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          )}
        >
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
            <Plus className="h-4 w-4" />
          </span>
          <span className="min-w-0">
            <span className="block text-sm font-medium">Request a backend</span>
            <span className="block text-xs text-muted-foreground">
              Need AWS, GCP, or another store? Let us know.
            </span>
          </span>
        </button>
      </div>

      <Dialog open={open} onOpenChange={(o) => !o && setActive(null)}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>
              {isRequest
                ? "Request a secret backend"
                : `${(active as Backend)?.name} integration`}
            </DialogTitle>
            <DialogDescription>
              {isRequest
                ? "External secret backends are in active development. Tell us which store you need and we'll prioritize it."
                : "This integration is in active development. It isn't available yet — check back soon."}
            </DialogDescription>
          </DialogHeader>
        </DialogContent>
      </Dialog>
    </div>
  );
}
