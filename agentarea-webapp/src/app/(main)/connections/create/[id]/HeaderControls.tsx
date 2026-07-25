"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";

/**
 * Subheader actions for the create-connection screen. Both the URL and Docker
 * forms create from here (consistent with the rest of the app). The active form
 * reports its readiness via a `mcp-create-state` event so these buttons can gate
 * on it; if no form reports, the buttons stay enabled.
 */
export default function MCPCreateHeaderControls() {
  const t = useTranslations("MCPServersPage.createInstance");
  const [createEnabled, setCreateEnabled] = useState(true);
  const [forceEnabled, setForceEnabled] = useState(true);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail || {};
      if (typeof detail.createEnabled === "boolean")
        setCreateEnabled(detail.createEnabled);
      if (typeof detail.forceEnabled === "boolean")
        setForceEnabled(detail.forceEnabled);
      if (typeof detail.creating === "boolean") setCreating(detail.creating);
    };
    document.addEventListener("mcp-create-state", handler);
    return () => document.removeEventListener("mcp-create-state", handler);
  }, []);

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
        disabled={!forceEnabled || creating}
      >
        {t("actions.forceCreate")}
      </Button>
      <Button
        size="xs"
        type="submit"
        form="mcp-instance-form"
        disabled={!createEnabled || creating}
        isLoading={creating}
      >
        {t("actions.createInstance")}
      </Button>
    </div>
  );
}
