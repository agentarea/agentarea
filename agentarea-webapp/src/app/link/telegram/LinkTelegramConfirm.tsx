"use client";

import { useActionState } from "react";
import { useTranslations } from "next-intl";
import { FocusStep } from "@/components/FocusCard";
import FormError from "@/components/FormError";
import { Button } from "@/components/ui/button";
import { acceptTelegramLinkAction, type LinkTelegramState } from "./actions";

/** The one confirmation that links the offered Telegram account, and what came of it. */
export default function LinkTelegramConfirm({
  code,
  bot,
  settingsHref,
}: {
  code: string;
  /** The bot's @handle, to name where to write next; "" when unknown. */
  bot: string;
  settingsHref: string;
}) {
  const t = useTranslations("LinkTelegram");
  const [state, formAction, pending] = useActionState<
    LinkTelegramState,
    FormData
  >(acceptTelegramLinkAction, { status: "idle" });
  const botName = bot || t("theBot");

  switch (state.status) {
    case "linked":
      return (
        <FocusStep
          kind="done"
          title={t("linkedTitle")}
          detail={t("linkedDetail", { bot: botName })}
        >
          <Button asChild variant="outline">
            <a href={settingsHref}>{t("openSettings")}</a>
          </Button>
        </FocusStep>
      );
    case "gone":
      return (
        <FocusStep
          kind="off"
          title={t("goneTitle")}
          detail={t("goneDetail", { bot: botName })}
        />
      );
    case "taken":
      return (
        <FocusStep
          kind="attention"
          title={t("takenTitle")}
          detail={t("takenDetail")}
        />
      );
  }

  return (
    <form action={formAction} className="flex flex-col gap-3">
      <input type="hidden" name="code" value={code} />
      {state.status === "failed" && <FormError>{state.message}</FormError>}
      <Button type="submit" isLoading={pending} className="w-full">
        {t("confirm")}
      </Button>
      <p className="text-center text-xs text-muted-foreground">{t("notYou")}</p>
    </form>
  );
}
