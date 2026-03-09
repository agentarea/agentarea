"use client";

import React, { useState } from "react";
import { useTranslations } from "next-intl";
import { Sparkles } from "lucide-react";
import type { BadgeSuggestion } from "./componets/BadgeSuggestions";
import { ChatWelcome } from "./componets/ChatWelcome";
import FullChat, { type Agent } from "./FullChat";

interface WorkplaceChatProps {
  initialAgent: Agent;
  availableAgents: Agent[];
  badgeSuggestions?: BadgeSuggestion[];
}

/**
 * Client wrapper for FullChat that handles agent switching
 * Receives initial agent and available agents from server
 */
export function WorkplaceChat({
  initialAgent,
  availableAgents,
  badgeSuggestions,
}: WorkplaceChatProps) {
  const t = useTranslations("Workplace.hero");
  const [selectedAgent, setSelectedAgent] = useState<Agent>(initialAgent);

  return (
    <FullChat
      agent={selectedAgent}
      availableAgents={availableAgents}
      onAgentChange={setSelectedAgent}
      startCentered
      badgeSuggestions={badgeSuggestions}
      welcomeComponent={<ChatWelcome icon={Sparkles} title={t("title")} />}
    />
  );
}
