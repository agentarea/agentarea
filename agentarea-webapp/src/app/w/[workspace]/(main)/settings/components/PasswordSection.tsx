"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { UiNodeGroupEnum, type UiNode, type UiText } from "@ory/client-fetch";
import { useOryFlow } from "@ory/elements-react";
import { useFormContext, useWatch } from "react-hook-form";
import { Button } from "@/components/ui/button";
import { PasswordInput } from "@/components/ui/password-input";
import {
  FieldErrors,
  FlowSuccess,
  MethodSubmit,
  useSavedHere,
} from "./FlowParts";
import { errorsOf, findInput } from "./oryNodes";
import SettingsRow from "./SettingsRow";
import { SettingsFooter, SettingsSection } from "./SettingsSection";

/** Kratos' default `min_password_length`; it re-checks and has the last word. */
const MIN_PASSWORD_LENGTH = 8;

export default function PasswordSection({ nodes }: { nodes: UiNode[] }) {
  const t = useTranslations("SettingsPage.security");
  const { flow } = useOryFlow();
  const { reset } = useFormContext();
  // The flow the editor was opened on. A newer flow in which Kratos took the
  // password folds the editor away.
  const [openedOn, setOpenedOn] = useState<typeof flow | null>(null);
  const updated = useSavedHere(nodes);
  const editing = openedOn !== null && !(updated && flow !== openedOn);

  const close = () => {
    reset();
    setOpenedOn(null);
  };

  return (
    <SettingsSection title={t("title")}>
      <SettingsRow
        title={t("password")}
        description={updated ? <FlowSuccess /> : t("passwordDescription")}
        below={
          editing && (
            <PasswordField
              messages={findInput(nodes, "password")?.messages}
              onCancel={close}
            />
          )
        }
      >
        {editing ? null : (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setOpenedOn(flow)}
          >
            {t("changePassword")}
          </Button>
        )}
      </SettingsRow>
      {editing && <PasswordFooter onCancel={close} />}
    </SettingsSection>
  );
}

const usePasswordShortfall = () => {
  const password = (useWatch({ name: "password" }) as string | undefined) ?? "";
  return {
    typed: password.length > 0,
    missing: MIN_PASSWORD_LENGTH - password.length,
  };
};

/** The new-password field with its length hint; with the footer, the only parts that re-render as you type. */
function PasswordField({
  messages,
  onCancel,
}: {
  messages: UiText[] | undefined;
  onCancel: () => void;
}) {
  const t = useTranslations("SettingsPage.security");
  const { register } = useFormContext();
  const { typed, missing } = usePasswordShortfall();
  const invalid = errorsOf(messages).length > 0;

  return (
    <div className="space-y-1.5 pt-1">
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
          {typed && missing > 0
            ? t("passwordMissing", { count: missing })
            : t("passwordHint", { count: MIN_PASSWORD_LENGTH })}
        </p>
      )}
    </div>
  );
}

function PasswordFooter({ onCancel }: { onCancel: () => void }) {
  const t = useTranslations("SettingsPage.security");
  const tCommon = useTranslations("Common");
  const {
    formState: { isSubmitting },
  } = useFormContext();
  const { missing } = usePasswordShortfall();

  return (
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
  );
}
