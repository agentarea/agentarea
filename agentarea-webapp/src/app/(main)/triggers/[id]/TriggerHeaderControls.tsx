"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { usePathname, useRouter } from "next/navigation";
import { Power, PowerOff } from "lucide-react";
import { toast } from "sonner";
import { useFormSubmittingState } from "@/app/(main)/agents/shared/useFormSubmittingState";
import DeleteButton from "@/components/DeleteButton/DeleteButton";
import { Button } from "@/components/ui/button";
import {
  deleteTriggerAction,
  disableTriggerAction,
  enableTriggerAction,
} from "./actions";

export default function TriggerHeaderControls({
  triggerId,
  triggerName,
  isActive,
}: {
  triggerId: string;
  triggerName: string;
  isActive: boolean;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const tCreate = useTranslations("TriggersPage.create");
  // The form only exists on the overview route; the executions and metrics tabs
  // share this header and have nothing to submit.
  const isOverview = pathname === `/triggers/${triggerId}`;
  const isSaving = useFormSubmittingState("create-trigger-form");
  const [isToggling, setIsToggling] = useState(false);
  const [active, setActive] = useState(isActive);
  const handleDelete = async (id: string) => {
    const result = await deleteTriggerAction(id);
    return result.error
      ? { error: { detail: [{ msg: result.error }] } }
      : { error: undefined };
  };

  const handleToggle = async () => {
    setIsToggling(true);
    try {
      const action = active ? disableTriggerAction : enableTriggerAction;
      const { error } = await action(triggerId);
      if (error) {
        toast.error(
          active ? "Failed to disable trigger" : "Failed to enable trigger"
        );
      } else {
        setActive(!active);
        toast.success(active ? "Trigger disabled" : "Trigger enabled");
        router.refresh();
      }
    } finally {
      setIsToggling(false);
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-2 py-1 sm:flex-nowrap">
      <Button
        size="xs"
        variant="outline"
        type="button"
        onClick={handleToggle}
        disabled={isToggling}
        isLoading={isToggling}
      >
        {active ? (
          <>
            <PowerOff />
            Disable
          </>
        ) : (
          <>
            <Power />
            Enable
          </>
        )}
      </Button>
      {isOverview && (
        <Button
          size="xs"
          type="submit"
          form="create-trigger-form"
          isLoading={isSaving}
          disabled={isSaving}
        >
          {tCreate("updateButton")}
        </Button>
      )}
      <DeleteButton
        size="xs"
        itemId={triggerId}
        itemName={triggerName}
        onDelete={handleDelete}
        redirectPath="/triggers"
        title="Delete Trigger"
        description={`Are you sure you want to delete "${triggerName}"? This action cannot be undone.`}
        successMessage="Trigger deleted"
        errorMessages={{
          failedToDelete: "Failed to delete trigger",
          unexpectedError: "Failed to delete trigger",
        }}
      />
    </div>
  );
}
