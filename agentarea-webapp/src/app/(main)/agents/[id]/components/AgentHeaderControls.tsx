"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { MessageSquare, Play } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useIsMobile } from "@/hooks/use-mobile";
import { useChat } from "../../shared/ChatContext";
import { useFormSubmittingState } from "../../shared/useFormSubmittingState";

/**
 * Right-hand controls of the agent header. On the settings / wallet forms it
 * is the "Save changes" submit; everywhere else it is the primary "New task"
 * shortcut (hidden on the new-task page itself and for catalog previews).
 */
export default function AgentHeaderControls({
  agentRef,
  isCatalog = false,
}: {
  agentRef: string;
  isCatalog?: boolean;
}) {
  const pathname = usePathname();
  const onSettings = pathname?.endsWith("/settings");
  const onWallet = pathname?.endsWith("/wallet");
  const onNewTask = pathname?.endsWith("/new-task");
  const tCommon = useTranslations("Common");
  const tAgents = useTranslations("AgentsPage");
  const isSubmitting = useFormSubmittingState(
    onWallet ? "wallet-form" : "agent-form"
  );
  const isMobile = useIsMobile();
  const { setIsChatSheetOpen } = useChat();

  if (onSettings || onWallet) {
    const formId = onWallet ? "wallet-form" : "agent-form";
    return (
      <div className="flex items-center gap-2 py-1">
        {isMobile && onSettings && (
          <Button
            variant="outline"
            size="xs"
            type="button"
            onClick={() => setIsChatSheetOpen(true)}
          >
            <MessageSquare />
          </Button>
        )}
        <Button size="xs" type="submit" form={formId} isLoading={isSubmitting}>
          {tCommon("saveChanges")}
        </Button>
      </div>
    );
  }

  if (isCatalog || onNewTask) return null;

  return (
    <div className="flex items-center gap-2 py-1">
      <Button
        asChild
        size="sm"
        className="h-7 gap-1.5 px-3 text-[12.5px] font-semibold"
      >
        <Link href={`/agents/${agentRef}/new-task`}>
          <Play strokeWidth={2} />
          {tAgents("newTask")}
        </Link>
      </Button>
    </div>
  );
}
