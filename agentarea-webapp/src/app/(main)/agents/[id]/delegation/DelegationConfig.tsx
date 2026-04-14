"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { Users } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { updateAgentAction } from "@/lib/server-actions";
import type { components } from "@/api/schema";

type Agent = {
  id: string;
  name: string;
  description?: string | null;
  status: string;
};

type ToolConfig = components["schemas"]["ToolConfigYAML"];

interface DelegationConfigProps {
  agentId: string;
  otherAgents: Agent[];
  connectedAgentNames: Set<string>;
  currentTools: ToolConfig[];
}

export function DelegationConfig({
  agentId,
  otherAgents,
  connectedAgentNames: initialConnected,
  currentTools,
}: DelegationConfigProps) {
  const t = useTranslations("AgentsPage");
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [connected, setConnected] = useState<Set<string>>(
    () => new Set(initialConnected)
  );
  const [isSaving, setIsSaving] = useState(false);

  const hasChanges =
    connected.size !== initialConnected.size ||
    [...connected].some((name) => !initialConnected.has(name));

  function toggleAgent(agentName: string) {
    setConnected((prev) => {
      const next = new Set(prev);
      if (next.has(agentName)) {
        next.delete(agentName);
      } else {
        next.add(agentName);
      }
      return next;
    });
  }

  async function handleSave() {
    setIsSaving(true);
    try {
      const nonAgentTools = currentTools.filter((t) => t.type !== "agent");
      const agentTools = [...connected].map((name) => ({
        type: "agent" as const,
        name,
      }));
      const tools = [...nonAgentTools, ...agentTools];

      await updateAgentAction(agentId, { tools });
      startTransition(() => {
        router.refresh();
      });
    } finally {
      setIsSaving(false);
    }
  }

  if (otherAgents.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
        <Users className="h-10 w-10 text-muted-foreground" />
        <p className="text-sm text-muted-foreground">
          No other agents in this workspace to delegate to.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-medium">{t("delegation")}</h3>
          <p className="text-xs text-muted-foreground">
            Enable delegation to allow this agent to start tasks on other
            agents.
          </p>
        </div>
        {hasChanges && (
          <Button
            size="sm"
            onClick={handleSave}
            disabled={isSaving || isPending}
          >
            {isSaving ? "Saving..." : "Save"}
          </Button>
        )}
      </div>

      <div className="divide-y divide-border rounded-md border">
        {otherAgents.map((agent) => (
          <div
            key={agent.id}
            className="flex items-center justify-between px-4 py-3"
          >
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium truncate">{agent.name}</p>
              {agent.description && (
                <p className="text-xs text-muted-foreground truncate">
                  {agent.description}
                </p>
              )}
            </div>
            <Switch
              checked={connected.has(agent.name)}
              onCheckedChange={() => toggleAgent(agent.name)}
              disabled={isSaving || isPending}
            />
          </div>
        ))}
      </div>
    </div>
  );
}
