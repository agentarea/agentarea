"use client";

import type { AgentResponse } from "@/api/client/types.gen";
import { useState, useTransition } from "react";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { useTranslations } from "next-intl";
import { Users } from "lucide-react";
import FormError from "@/components/FormError";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { apiErrorMessage, formatApiError } from "@/lib/api-errors";
import { updateAgentAction } from "@/lib/server-actions";
import { withDelegates } from "../../shared/delegationTools";

type Agent = {
  id: string;
  name: string;
  description?: string | null;
  status: string;
};

interface DelegationConfigProps {
  agentId: string;
  otherAgents: Agent[];
  connectedAgentNames: Set<string>;
  currentTools: NonNullable<AgentResponse["tools"]>;
}

export function DelegationConfig({
  agentId,
  otherAgents,
  connectedAgentNames: initialConnected,
  currentTools,
}: DelegationConfigProps) {
  const t = useTranslations("AgentsPage");
  const tCommon = useTranslations("Common");
  const router = useWorkspaceRouter();
  const [isPending, startTransition] = useTransition();
  const [connected, setConnected] = useState<Set<string>>(
    () => new Set(initialConnected)
  );
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const hasChanges =
    connected.size !== initialConnected.size ||
    [...connected].some((name) => !initialConnected.has(name));

  function toggleAgent(agentName: string) {
    setError(null);
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
    setError(null);
    try {
      const result = await updateAgentAction(agentId, {
        tools: withDelegates(currentTools, connected),
      });
      if (result.error || !result.data) {
        setError(apiErrorMessage(result, t("delegationPage.saveFailed")));
        return;
      }
      startTransition(() => {
        router.refresh();
      });
    } catch (err) {
      console.error("Failed to save delegation", err);
      setError(`${t("delegationPage.saveFailed")}: ${formatApiError(err)}`);
    } finally {
      setIsSaving(false);
    }
  }

  if (otherAgents.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
        <Users className="h-10 w-10 text-muted-foreground" />
        <p className="text-sm text-muted-foreground">
          {t("delegationPage.noOtherAgents")}
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
            {t("delegationPage.description")}
          </p>
        </div>
        {hasChanges && (
          <Button
            size="sm"
            onClick={handleSave}
            disabled={isSaving || isPending}
          >
            {isSaving ? t("delegationPage.saving") : tCommon("save")}
          </Button>
        )}
      </div>

      {error && <FormError>{error}</FormError>}

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
