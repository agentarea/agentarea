"use client";

import { useTranslations } from "next-intl";
import { Plus } from "lucide-react";
import { useFormSubmittingState } from "@/app/w/[workspace]/(main)/agents/shared/useFormSubmittingState";
import { Button } from "@/components/ui/button";
import { ADD_MCP_SERVER_FORM_ID } from "./form";

export default function AddMCPServerHeaderControls() {
  const t = useTranslations("MCPServersPage.newServer");
  const isSubmitting = useFormSubmittingState(ADD_MCP_SERVER_FORM_ID);

  return (
    <div className="flex items-center gap-2 py-1">
      <Button
        size="xs"
        type="submit"
        form={ADD_MCP_SERVER_FORM_ID}
        isLoading={isSubmitting}
        disabled={isSubmitting}
      >
        <Plus />
        {t("submit")}
      </Button>
    </div>
  );
}
