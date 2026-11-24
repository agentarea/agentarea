import { getFormatter, getTranslations } from "next-intl/server";
import { TelegramTile } from "@/components/TelegramTile";
import { Button } from "@/components/ui/button";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { listExternalIdentities } from "@/lib/api";
import { telegramAccountLabel } from "@/lib/telegram-account";
import {
  linkTelegramAction,
  unlinkMessengerAction,
} from "../messenger-actions";
import SettingsRow from "./SettingsRow";
import { SettingsSection } from "./SettingsSection";

const telegramTile = <TelegramTile />;

/**
 * Messenger accounts the platform recognises as the caller. A bot answers only
 * linked people it is allowed to; linking starts from the bot itself, whose
 * reply links the account in one confirmation.
 */
export default async function MessengersSection({
  linkBot,
}: {
  /** The bot an older reply sent the caller here from; linking goes through it. */
  linkBot?: string;
}) {
  const t = await getTranslations("SettingsPage.messengers");
  const format = await getFormatter();
  const result = await listExternalIdentities();
  const links = (result.data ?? []).filter(
    (link) => link.provider === "telegram"
  );

  return (
    <div id="messengers">
      <SettingsSection
        title={t("title")}
        description={
          links.length > 0
            ? `${t("description")} ${t("linkAnotherHint")}`
            : t("description")
        }
      >
        {links.map((link) => {
          const named = Boolean(link.username || link.display_name);
          const date = format.dateTime(new Date(link.linked_at), {
            dateStyle: "medium",
          });
          return (
            <SettingsRow
              key={link.id}
              tile={telegramTile}
              title={telegramAccountLabel(link)}
              description={
                <StatusIndicator kind="active" size="sm" className="mt-0.5">
                  {named
                    ? t("linkedAs", { id: link.external_id, date })
                    : t("linkedOn", { date })}
                </StatusIndicator>
              }
            >
              <form action={unlinkMessengerAction}>
                <input type="hidden" name="id" value={link.id} />
                <Button type="submit" variant="outline" size="xs">
                  {t("unlink")}
                </Button>
              </form>
            </SettingsRow>
          );
        })}
        {(linkBot || links.length === 0) && (
          <SettingsRow
            tile={telegramTile}
            title="Telegram"
            description={
              linkBot ? t("linkThrough", { bot: `@${linkBot}` }) : t("howTo")
            }
          >
            {linkBot && (
              <form action={linkTelegramAction}>
                <input type="hidden" name="bot" value={linkBot} />
                <Button type="submit" size="xs">
                  {t("link")}
                </Button>
              </form>
            )}
          </SettingsRow>
        )}
      </SettingsSection>
    </div>
  );
}
