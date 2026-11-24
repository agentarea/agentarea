"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Loader2 } from "lucide-react";
import { Controller, useForm, useWatch } from "react-hook-form";
import type { Senders } from "@/api/client/types.gen";
import { Button } from "@/components/ui/button";
import { updateStreamSourceSendersAction } from "../actions";
import {
  fromSenders,
  sendersReady,
  toSenders,
  type SendersFormValue,
} from "../senders";
import SendersField from "./SendersField";

interface SourceSendersForm {
  senders: SendersFormValue;
}

/** Who may write to an added bot, changed in place. */
export default function SourceSenders({
  streamId,
  sourceId,
  senders,
  chosenByOther,
}: {
  streamId: string;
  sourceId: string;
  senders: Senders | null | undefined;
  chosenByOther: boolean;
}) {
  const t = useTranslations("EventsPage.sources.senders");
  const [error, setError] = useState<string | null>(null);
  const {
    control,
    handleSubmit,
    reset,
    formState: { isDirty, isSubmitting },
  } = useForm<SourceSendersForm>({
    defaultValues: { senders: fromSenders(senders) },
  });
  const value = useWatch({ control, name: "senders" });

  const save = handleSubmit(async (form) => {
    setError(null);
    const result = await updateStreamSourceSendersAction(
      streamId,
      sourceId,
      toSenders(form.senders)
    );
    if (result.error) {
      setError(result.error);
      return;
    }
    reset(form);
  });

  // Saving someone else's choice makes it yours, so it can always be saved.
  const savable = isDirty || chosenByOther;

  return (
    <form onSubmit={save} className="space-y-2">
      <Controller
        control={control}
        name="senders"
        render={({ field }) => (
          <SendersField
            id={`source-${sourceId}`}
            value={field.value}
            chosenByOther={chosenByOther && !isDirty}
            onChange={(next) => {
              field.onChange(next);
              setError(null);
            }}
          />
        )}
      />
      {savable && (
        <Button
          type="submit"
          size="xs"
          disabled={isSubmitting || !sendersReady(value)}
        >
          {isSubmitting && <Loader2 className="animate-spin" />}
          {t("save")}
        </Button>
      )}
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}
