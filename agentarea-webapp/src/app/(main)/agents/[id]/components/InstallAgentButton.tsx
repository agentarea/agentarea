"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { StartAgentButton } from "@/components/ui/start-agent-button";
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
    <div className="flex w-full max-w-[210px] flex-col items-start gap-1.5">
      <StartAgentButton
        size="xs"
        onClick={onInstall}
        isLoading={pending}
      >
        Add to workspace
      </StartAgentButton>
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}
