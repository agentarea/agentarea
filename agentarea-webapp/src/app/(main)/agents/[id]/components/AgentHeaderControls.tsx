"use client";

import { MessageSquare } from "lucide-react";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { useIsMobile } from "@/hooks/use-mobile";
import { useFormSubmittingState } from "../../shared/useFormSubmittingState";
import { useChat } from "../../shared/ChatContext";

export default function AgentHeaderControls() {
  const pathname = usePathname();
  const onSettings = pathname?.endsWith("/settings");
  const tCommon = useTranslations("Common");
  const isSubmitting = useFormSubmittingState();
  const isMobile = useIsMobile();
  const { setIsChatSheetOpen } = useChat();

  if (!onSettings) return null;

  return (
    <div className="flex items-center gap-2 py-1">
      {isMobile && (
        <Button
          variant="outline"
          size="xs"
          type="button"
          onClick={() => setIsChatSheetOpen(true)}
        >
          <MessageSquare className="h-4 w-4" />
        </Button>
      )}
      <Button size="xs" type="submit" form="agent-form" isLoading={isSubmitting}>
        {tCommon("saveChanges")}
      </Button>
    </div>
  );
}
