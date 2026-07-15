"use client";

import React, { useState } from "react";
import { useTranslations } from "next-intl";
import { Sparkles } from "lucide-react";
import type { BadgeSuggestion } from "./componets/BadgeSuggestions";
import { ChatWelcome } from "./componets/ChatWelcome";
import FullChat, {
  type Agent,
  type ProjectOption,
  type TaskPolicyOption,
} from "./FullChat";

interface WorkplaceChatProps {
  initialAgent: Agent;
  availableAgents: Agent[];
  availableProjects?: ProjectOption[];
  availableTaskPolicies?: TaskPolicyOption[];
  badgeSuggestions?: BadgeSuggestion[];
}

/**
 * Client wrapper for FullChat that handles agent switching
 * Receives initial agent and available agents from server
 */
export function WorkplaceChat({
  initialAgent,
  availableAgents,
  availableProjects,
  availableTaskPolicies,
  badgeSuggestions,
}: WorkplaceChatProps) {
  const t = useTranslations("Workplace.hero");
  const [selectedAgent, setSelectedAgent] = useState<Agent>(initialAgent);

  // The workspace chat starts without a task in the URL. Once the first message
  // creates a task, adopt its URL so a refresh reconnects to the live stream and
  // follow-up messages have a task to target (instead of being lost in memory).
  //
  // Use the native History API (supported by the App Router) instead of
  // router.replace: it rewrites the URL in place WITHOUT re-running the route or
  // unmounting this chat, so the in-flight event stream keeps going and the UI
  // doesn't flicker. A hard refresh still lands on /tasks/[id], which replays
  // history from the DB.
  const handleTaskCreated = React.useCallback((taskId: string) => {
    if (typeof window !== "undefined") {
      window.history.replaceState(null, "", `/tasks/${taskId}`);
    }
  }, []);

  return (
    <FullChat
      agent={selectedAgent}
      availableAgents={availableAgents}
      onAgentChange={setSelectedAgent}
      availableProjects={availableProjects}
      availableTaskPolicies={availableTaskPolicies}
      startCentered
      badgeSuggestions={badgeSuggestions}
      welcomeComponent={<ChatWelcome icon={Sparkles} title={t("title")} />}
      onTaskCreated={handleTaskCreated}
    />
  );
}
