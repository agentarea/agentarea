import { redirect } from "next/navigation";
import { getPersonalWorkspacePath } from "@/lib/workspace-context";

/**
 * Where a bot sends someone it does not recognise. The bot cannot know their
 * workspace, so this lands them in the personal one, on the settings section
 * that links Telegram through the bot they came from.
 */
export default async function LinkTelegramPage({
  searchParams,
}: {
  searchParams: Promise<{ bot?: string }>;
}) {
  const { bot } = await searchParams;
  const query = bot ? `?link_telegram=${encodeURIComponent(bot)}` : "";
  redirect(await getPersonalWorkspacePath(`/settings${query}#messengers`));
}
