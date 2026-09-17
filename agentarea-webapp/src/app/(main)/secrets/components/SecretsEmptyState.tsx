"use client";

import { useState } from "react";
import EmptyState from "@/components/EmptyState";
import { CreateSecretDialog } from "./CreateSecretDialog";

/**
 * Empty state whose action opens the create dialog. The list itself is a
 * server component, so the dialog's open state has to live here.
 */
export function SecretsEmptyState() {
  const [open, setOpen] = useState(false);

  return (
    <>
      <EmptyState
        title="No secrets yet"
        description="Nothing here holds a credential. Create a secret to reuse it across LLM providers and API connections, instead of pasting the same key into each one."
        iconsType="mcp"
        action={{ label: "Create secret", onClick: () => setOpen(true) }}
      />
      <CreateSecretDialog open={open} onOpenChange={setOpen} showTrigger={false} />
    </>
  );
}
