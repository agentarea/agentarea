"use client";

import React from "react";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";

export default function AgentHeaderControls() {
  const pathname = usePathname();
  const onSettings = pathname?.endsWith("/settings");
  const tCommon = useTranslations("Common");

  return (
    <div className="flex items-center gap-2 py-1">
      {onSettings && (
        <Button size="xs" type="submit" form="agent-form">
          {tCommon("saveChanges")}
        </Button>
      )}
    </div>
  );
}


