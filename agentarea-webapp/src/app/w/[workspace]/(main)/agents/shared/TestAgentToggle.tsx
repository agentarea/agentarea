"use client";

import { useTranslations } from "next-intl";
import { MessageSquare } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useChat } from "./ChatContext";

export default function TestAgentToggle() {
  const { isChatOpen, setIsChatOpen } = useChat();
  const t = useTranslations("AgentsPage.form");

  return (
    <Button
      variant={isChatOpen ? "secondary" : "outline"}
      size="xs"
      type="button"
      aria-pressed={isChatOpen}
      onClick={() => setIsChatOpen(!isChatOpen)}
    >
      <MessageSquare />
      <span className="hidden sm:inline">{t("testAgent")}</span>
    </Button>
  );
}
