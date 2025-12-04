"use client";

import React, { useState } from "react";
import FullChat, { type Agent } from "./FullChat";
import type { BadgeSuggestion } from "./componets/BadgeSuggestions";

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
  const [selectedAgent, setSelectedAgent] = useState<Agent>(initialAgent);

  return (
    <FullChat
      agent={selectedAgent}
      availableAgents={availableAgents}
      onAgentChange={setSelectedAgent}
      startCentered
      badgeSuggestions={badgeSuggestions}
    />
  );
}
