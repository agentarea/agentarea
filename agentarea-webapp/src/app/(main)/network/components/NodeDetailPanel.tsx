"use client";

import { X, ExternalLink, Bot, Plug, Sparkles, Zap } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import Link from "next/link";

interface NetworkNodeData {
  id: string;
  type: "agent" | "mcp_instance" | "skill" | "trigger";
  label: string;
  status?: string | null;
  metadata: Record<string, any>;
}

const TYPE_CONFIG = {
  agent: { icon: Bot, color: "text-blue-500", href: (id: string) => `/agents/${id}` },
  mcp_instance: { icon: Plug, color: "text-green-500", href: (id: string) => `/mcp-servers/${id}` },
  skill: { icon: Sparkles, color: "text-purple-500", href: (id: string) => `/skills/${id}` },
  trigger: { icon: Zap, color: "text-amber-500", href: (id: string) => `/triggers/${id}` },
};

export default function NodeDetailPanel({
  node,
  onClose,
}: {
  node: NetworkNodeData;
  onClose: () => void;
}) {
  const config = TYPE_CONFIG[node.type];
  const Icon = config.icon;

  return (
    <div className="absolute bottom-4 left-4 z-10 w-72 rounded-lg border bg-white p-4 shadow-lg dark:bg-zinc-800 dark:border-zinc-700">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2">
          <Icon className={`h-5 w-5 ${config.color}`} />
          <div>
            <h3 className="text-sm font-semibold">{node.label}</h3>
            <p className="text-xs text-muted-foreground capitalize">
              {node.type.replace("_", " ")}
            </p>
          </div>
        </div>
        <Button variant="ghost" size="icon" className="h-6 w-6" onClick={onClose}>
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>

      {node.status && (
        <div className="mt-3">
          <Badge
            variant={
              node.status === "active" || node.status === "running"
                ? "default"
                : "secondary"
            }
          >
            {node.status}
          </Badge>
        </div>
      )}

      {Object.keys(node.metadata).length > 0 && (
        <div className="mt-3 space-y-1.5">
          {Object.entries(node.metadata).map(([key, value]) => (
            <div key={key} className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">{key.replace(/_/g, " ")}</span>
              <span className="font-medium truncate ml-2 max-w-[140px]">
                {typeof value === "object" ? JSON.stringify(value) : String(value)}
              </span>
            </div>
          ))}
        </div>
      )}

      <div className="mt-3 pt-3 border-t">
        <Link href={config.href(node.id)}>
          <Button variant="outline" size="sm" className="w-full gap-1.5 text-xs">
            <ExternalLink className="h-3 w-3" />
            Open {node.type.replace("_", " ")}
          </Button>
        </Link>
      </div>
    </div>
  );
}
