"use server";

import { getTranslations } from "next-intl/server";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { zTelegramLinkRequest } from "@/api/client/zod.gen";
import { startTelegramLink, unlinkExternalIdentity } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";
import { requestWorkspacePath } from "@/lib/workspace-request";

/** Leave for Telegram with a single-use code; the bot then asks to confirm. */
export async function linkTelegramAction(formData: FormData): Promise<void> {
  const parsed = zTelegramLinkRequest.safeParse({ bot: formData.get("bot") });
  if (!parsed.success) {
    throw new Error("linkTelegramAction needs a bot username");
  }
  const result = await startTelegramLink(parsed.data.bot);
  if (result.error || !result.data) {
    const t = await getTranslations("SettingsPage.messengers");
    throw new Error(apiErrorMessage(result, t("linkFailed")));
  }
  redirect(result.data.url);
}

export async function unlinkMessengerAction(formData: FormData): Promise<void> {
  const id = formData.get("id");
  if (typeof id !== "string" || !id) {
    throw new Error("unlinkMessengerAction needs an identity id");
  }
  const result = await unlinkExternalIdentity(id);
  if (result.error) {
    const t = await getTranslations("SettingsPage.messengers");
    throw new Error(apiErrorMessage(result, t("unlinkFailed")));
  }
  revalidatePath(await requestWorkspacePath("/settings"));
}
