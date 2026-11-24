"use client";

import { useTranslations } from "next-intl";
import { UserCheck } from "lucide-react";
import FormLabel from "@/components/FormLabel/FormLabel";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Textarea } from "@/components/ui/textarea";
import {
  invalidSenderIds,
  type SendersChoice,
  type SendersFormValue,
} from "../senders";

/**
 * Who may write to a bot: only whoever chooses it, or a list of account ids
 * that person answers for. "Members" is offered only to a source that already
 * admits them. `chosenByOther` words the saved choice for a viewer who did not
 * make it.
 */
export default function SendersField({
  id,
  value,
  onChange,
  chosenByOther = false,
}: {
  id: string;
  value: SendersFormValue;
  onChange: (next: SendersFormValue) => void;
  chosenByOther?: boolean;
}) {
  const t = useTranslations("EventsPage.sources.senders");
  const choices: SendersChoice[] =
    value.allow === "members" ? ["owner", "ids", "members"] : ["owner", "ids"];
  const invalid = value.allow === "ids" ? invalidSenderIds(value.ids) : [];

  return (
    <div className="space-y-2">
      <FormLabel icon={UserCheck}>{t("label")}</FormLabel>
      <SegmentedControl<SendersChoice>
        layoutId={`${id}-senders`}
        value={value.allow}
        onChange={(allow) => onChange({ ...value, allow })}
        items={choices.map((choice) => ({
          value: choice,
          label:
            choice === "owner" && chosenByOther
              ? t("choices.ownerOther")
              : t(`choices.${choice}`),
        }))}
      />
      {value.allow === "ids" && (
        <Textarea
          id={`${id}-ids`}
          aria-label={t("idsLabel")}
          value={value.ids}
          placeholder={t("idsPlaceholder")}
          rows={2}
          className="font-mono"
          onChange={(event) => onChange({ ...value, ids: event.target.value })}
        />
      )}
      {invalid.length > 0 ? (
        <p role="alert" className="text-xs text-destructive">
          {t("invalidIds", { ids: invalid.join(", ") })}
        </p>
      ) : (
        <p className="note">
          {chosenByOther && value.allow !== "members"
            ? t(`hints.${value.allow}Other`)
            : t(`hints.${value.allow}`)}
        </p>
      )}
    </div>
  );
}
