"use server";

import { getTranslations } from "next-intl/server";
import { zTelegramLinkOfferRequest } from "@/api/client/zod.gen";
import { acceptTelegramLinkOffer } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";

export type LinkTelegramState =
  | { status: "idle" }
  | { status: "linked" }
  | { status: "gone" }
  | { status: "taken" }
  | { status: "foreign" }
  | { status: "failed"; message: string };

/** Link the Telegram account the bot offered the code to, the person having confirmed it. */
export async function acceptTelegramLinkAction(
  _previous: LinkTelegramState,
  form: FormData
): Promise<LinkTelegramState> {
  const parsed = zTelegramLinkOfferRequest.safeParse({
    code: form.get("code"),
  });
  if (!parsed.success) {
    return { status: "gone" };
  }
  const result = await acceptTelegramLinkOffer(parsed.data.code);
  if (!result.error) return { status: "linked" };
  if (result.status === 404) return { status: "gone" };
  if (result.status === 409) return { status: "taken" };
  if (result.status === 403) return { status: "foreign" };
  console.error("[link/telegram] accept refused:", result.error);
  const t = await getTranslations("LinkTelegram");
  return { status: "failed", message: apiErrorMessage(result, t("failed")) };
}
