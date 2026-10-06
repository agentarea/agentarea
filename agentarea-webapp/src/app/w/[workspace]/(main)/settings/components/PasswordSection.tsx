"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { UiNodeGroupEnum, type UiNode, type UiText } from "@ory/client-fetch";
import { useOryFlow } from "@ory/elements-react";
import { useFormContext, useWatch } from "react-hook-form";
import { Button } from "@/components/ui/button";
import { PasswordInput } from "@/components/ui/password-input";
import { FieldErrors, FlowSuccess, MethodSubmit } from "./FlowParts";
import { errorsOf, findInput, submitAccepted } from "./oryNodes";
import SettingsRow from "./SettingsRow";
import { SettingsFooter, SettingsSection } from "./SettingsSection";

/** Kratos' default `min_password_length`; it re-checks and has the last word. */
const MIN_PASSWORD_LENGTH = 8;

export default function PasswordSection({ nodes }: { nodes: UiNode[] }) {
  const t = useTranslations("SettingsPage.security");
  const { flow } = useOryFlow();
  const {
    reset,
    formState: { isSubmitSuccessful },
  } = useFormContext();
  const [open, setOpen] = useState(false);
  const updated = isSubmitSuccessful && submitAccepted(flow, nodes);
  // The editor folds away once Kratos has taken the new password.
  const editing = open && !updated;

  // `reset` also clears the last submit, so a new attempt starts unflagged.
  const toggle = (next: boolean) => {
    reset();
    setOpen(next);
  };

  return (
    <SettingsSection title={t("title")}>
      <SettingsRow
        title={t("password")}
        description={updated ? <FlowSuccess /> : t("passwordDescription")}
      >
        {editing ? null : (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => toggle(true)}
          >
            {t("changePassword")}
          </Button>
        )}
      </SettingsRow>
      {editing && (
        <PasswordEditor
          messages={findInput(nodes, "password")?.messages}
          onCancel={() => toggle(false)}
        />
      )}
    </SettingsSection>
  );
}

/** The new-password field with its length hint; the only part that re-renders as you type. */
function PasswordEditor({
  messages,
  onCancel,
}: {
  messages: UiText[] | undefined;
  onCancel: () => void;
}) {
  const t = useTranslations("SettingsPage.security");
  const tCommon = useTranslations("Common");
  const {
    register,
    formState: { isSubmitting },
  } = useFormContext();
  const password = (useWatch({ name: "password" }) as string | undefined) ?? "";
  const missing = MIN_PASSWORD_LENGTH - password.length;
  const invalid = errorsOf(messages).length > 0;

  return (
    <>
      <div className="space-y-1.5 border-b border-border/60 px-4 pb-4">
        <PasswordInput
          aria-label={t("newPassword")}
          placeholder={t("newPassword")}
          autoComplete="new-password"
          autoFocus
          aria-invalid={invalid || undefined}
          onKeyDown={(event) => {
            if (event.key === "Escape") onCancel();
          }}
          {...register("password")}
        />
        {invalid ? (
          <FieldErrors messages={messages} />
        ) : (
          <p className="text-xs text-muted-foreground">
            {password && missing > 0
              ? t("passwordMissing", { count: missing })
              : t("passwordHint", { count: MIN_PASSWORD_LENGTH })}
          </p>
        )}
      </div>
      <SettingsFooter>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={isSubmitting}
          onClick={onCancel}
        >
          {tCommon("cancel")}
        </Button>
        <MethodSubmit method={UiNodeGroupEnum.Password} disabled={missing > 0}>
          {t("updatePassword")}
        </MethodSubmit>
      </SettingsFooter>
    </>
  );
}
