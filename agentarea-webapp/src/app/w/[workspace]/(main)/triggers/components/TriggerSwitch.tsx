"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Switch } from "@/components/ui/switch";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { formatApiError } from "@/lib/api-errors";
import { disableTriggerAction, enableTriggerAction } from "../[id]/actions";

/**
 * Turns a trigger on or off from its row. Flips at once and settles on what
 * the server answers; a refusal flips it back and says why on hover.
 */
export default function TriggerSwitch({
  triggerId,
  name,
  active,
  disabled,
}: {
  triggerId: string;
  name: string;
  active: boolean;
  disabled?: boolean;
}) {
  const t = useTranslations("TriggersPage");
  const router = useWorkspaceRouter();
  const [on, setOn] = useState(active);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggle = async (next: boolean) => {
    setOn(next);
    setBusy(true);
    setError(null);
    try {
      const result = await (next ? enableTriggerAction : disableTriggerAction)(
        triggerId
      );
      if (result.error) {
        setOn(!next);
        setError(result.error);
        return;
      }
      if (typeof result.data?.is_active === "boolean") {
        setOn(result.data.is_active);
      }
      router.refresh();
    } catch (err) {
      setOn(!next);
      setError(
        `${t(next ? "error.enableFailed" : "error.disableFailed")}: ${formatApiError(err)}`
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <span
      className="inline-flex"
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => e.stopPropagation()}
      title={error ?? undefined}
    >
      <Switch
        size="xs"
        checked={on}
        disabled={disabled || busy}
        onCheckedChange={(next) => void toggle(next)}
        aria-label={t(on ? "switch.turnOff" : "switch.turnOn", { name })}
        className={error ? "ring-2 ring-destructive/60" : undefined}
      />
    </span>
  );
}
