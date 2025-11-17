"use client";

import { MessageSquare } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useIsMobile } from "@/hooks/use-mobile";
import { useFormSubmittingState } from "../shared/useFormSubmittingState";
import { useChat } from "../shared/ChatContext";

export default function CreateAgentHeaderControls({
  label,
}: {
  label?: string;
}) {
  const isSubmitting = useFormSubmittingState();
  const isMobile = useIsMobile();
  const { setIsChatSheetOpen } = useChat();

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
        {label}
      </Button>
    </div>
  );
}
