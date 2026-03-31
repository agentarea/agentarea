"use client";

import { X, Bot, Plug, Sparkles, Zap } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import ModelInfo from "@/components/TaskInfoPanel/components/ModelInfo";
import Section from "@/components/TaskInfoPanel/components/Section";
import ActionLink from "@/components/TaskInfoPanel/components/ActionLink";
import { ScrollArea } from "@/components/ui/scroll-area";

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
    <div className="absolute bottom-4 left-4 z-10 w-80 rounded-lg border bg-white shadow-xl dark:bg-zinc-900 dark:border-zinc-800 flex flex-col max-h-[70vh]">
      <div className="flex items-start justify-between p-4 pb-2">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10">
            <Icon className={`h-5 w-5 ${config.color}`} />
          </div>
          <div>
            <h3 className="text-sm font-semibold leading-none">{node.label}</h3>
            <p className="text-[10px] text-muted-foreground uppercase tracking-wider mt-1">
              {node.type.replace("_", " ")}
            </p>
          </div>
        </div>
        <Button variant="ghost" size="icon" className="h-6 w-6 -mr-1" onClick={onClose}>
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>

      <ScrollArea className="flex-1 px-4 pb-4">
        <div className="space-y-3 pt-2">
          {node.type === "agent" ? (
            <ModelInfo
              agentId={node.id}
              hideAgentHeader={true}
              hideDescription={true}
              hideInstruction={true}
              hideOpenButton={true}
            />
          ) : (
            <>
              {node.status && (
                <Section title="Status">
                  <Badge
                    variant={
                      node.status === "active" || node.status === "running"
                        ? "default"
                        : "secondary"
                    }
                    className="text-[10px] uppercase font-normal tracking-wider"
                  >
                    {node.status}
                  </Badge>
                </Section>
              )}

              {Object.keys(node.metadata).length > 0 && (
                <Section title="Metadata">
                  <div className="space-y-1.5">
                    {Object.entries(node.metadata).map(([key, value]) => (
                      <div key={key} className="flex items-center justify-between text-[11px]">
                        <span className="text-muted-foreground">{key.replace(/_/g, " ")}</span>
                        <span className="font-medium truncate ml-2 max-w-[140px]">
                          {typeof value === "object" ? JSON.stringify(value) : String(value)}
                        </span>
                      </div>
                    ))}
                  </div>
                </Section>
              )}
            </>
          )}

          <div className="pt-1">
            <ActionLink href={config.href(node.id)}>
              Open {node.type.replace("_", " ")}
            </ActionLink>
          </div>
        </div>
      </ScrollArea>
    </div>
  );
}
