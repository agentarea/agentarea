"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { installAgentAction } from "@/lib/server-actions";
import { agentPath } from "@/types";

/**
 * "Add to workspace" CTA for a read-only catalog agent. Installing forks a real
 * tenant copy (copy-on-write) and navigates to that owned agent.
 */
export function InstallAgentButton({ agentRef }: { agentRef: string }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [error, setError] = useState<string | null>(null);

  const onInstall = () => {
    setError(null);
    start(async () => {
      const res = await installAgentAction(agentRef);
      const installed = res?.data as
        | { slug?: string | null; id: string }
        | undefined;
      if (res?.error || !installed) {
        setError("Couldn't add this agent to your workspace. Please try again.");
        return;
      }
      router.push(agentPath(installed));
      router.refresh();
    });
  };

  return (
    <div className="flex flex-col items-start gap-1.5">
      <Button
        size="sm"
        onClick={onInstall}
        isLoading={pending}
        className="gap-2"
      >
        <Plus className="h-4 w-4" />
        Add to workspace
      </Button>
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}
