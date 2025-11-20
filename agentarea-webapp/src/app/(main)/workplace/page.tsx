import React from "react";
import AuthGuard from "@/components/auth/AuthGuard";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import FullChat from "@/components/Chat/FullChat";

export default function WorkplacePage() {
  const badgeSuggestions = [
    { label: "Create new agent for my project", text: "Create new agent for my project" },
    { label: "Add task for agent", text: "Create new task for agent - @" },
    { label: "Ask agent about my project", text: "Ask agent about my project" },
    { label: "Something about my project", text: "Something about my project" },
    { label: "Test test :)", text: "Test test lala" },
  ];

  return (
    <AuthGuard>
      <ContentBlock
        header={{
          breadcrumb: [{ label: "Workplace", href: "/workplace" }],
        }}
      >
        <FullChat 
          agent={{ id: "1", name: "Your main assistant" }} 
          startCentered 
          badgeSuggestions={badgeSuggestions}
        />
      </ContentBlock>
    </AuthGuard>
  );
}
