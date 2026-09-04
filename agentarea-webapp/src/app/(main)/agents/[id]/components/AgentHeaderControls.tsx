"use client";

import { useTranslations } from "next-intl";
import { usePathname } from "next/navigation";
import { MessageSquare } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useIsMobile } from "@/hooks/use-mobile";
import { useChat } from "../../shared/ChatContext";
import { useFormSubmittingState } from "../../shared/useFormSubmittingState";

export default function AgentHeaderControls() {
  const pathname = usePathname();
  const onSettings = pathname?.endsWith("/settings");
  const onWallet = pathname?.endsWith("/wallet");
  const tCommon = useTranslations("Common");
  const isSubmitting = useFormSubmittingState(
    onWallet ? "wallet-form" : "agent-form"
  );
  const isMobile = useIsMobile();
  const { setIsChatSheetOpen } = useChat();

  if (!onSettings && !onWallet) return null;

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
