/** A Telegram account as the API names it: the id, and what Telegram showed when it was linked. */
export interface TelegramAccountNames {
  external_id: string;
  username?: string | null;
  display_name?: string | null;
}

/** `@username · First Last`, either part alone, or the numeric id when Telegram named nothing. */
export function telegramAccountLabel(account: TelegramAccountNames): string {
  const parts = [
    account.username ? `@${account.username}` : null,
    account.display_name?.trim() || null,
  ].filter((part): part is string => Boolean(part));
  return parts.length > 0 ? parts.join(" · ") : account.external_id;
}
