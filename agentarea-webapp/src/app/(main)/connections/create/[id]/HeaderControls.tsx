"use client";

import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";

export default function MCPCreateHeaderControls() {
  const t = useTranslations("MCPServersPage.createInstance");

  const handleForceCreate = () => {
    const form = document.getElementById("mcp-instance-form");
    if (form) {
      const evt = new Event("mcp-force-create", { bubbles: true });
      form.dispatchEvent(evt);
    }
  };

  return (
    <div className="flex items-center gap-2 py-1">
      <Button
        size="xs"
        variant="destructive"
        type="button"
        onClick={handleForceCreate}
      >
        {t("actions.forceCreate")}
      </Button>
      <Button size="xs" type="submit" form="mcp-instance-form">
        {t("actions.createInstance")}
      </Button>
    </div>
  );
}
