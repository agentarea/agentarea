import { getFormatter, getTranslations } from "next-intl/server";
import { TelegramIcon } from "@/components/brand-icons";
import { Button } from "@/components/ui/button";
import { EntityAvatar } from "@/components/ui/entity-avatar";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { listExternalIdentities } from "@/lib/api";
import { deterministicHue } from "@/lib/avatar-hue";
import {
  linkTelegramAction,
  unlinkMessengerAction,
} from "../messenger-actions";
import SettingsRow from "./SettingsRow";
import { SettingsSection } from "./SettingsSection";

const telegramTile = (
  <EntityAvatar
    size={32}
    hue={deterministicHue("telegram")}
    iconScale={0.56}
    icon={<TelegramIcon className="text-foreground" />}
    aria-hidden
  />
);

/**
 * Messenger accounts the platform recognises as the caller. A bot answers only
 * linked people it is allowed to; linking starts from the bot itself, which
 * sends the person here with its username.
 */
export default async function MessengersSection({
  linkBot,
}: {
  /** The bot that sent the caller here; linking goes through it. */
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
      <SettingsSection title={t("title")} description={t("description")}>
        {links.map((link) => (
          <SettingsRow
            key={link.id}
            tile={telegramTile}
            title="Telegram"
            description={
              <StatusIndicator kind="active" size="sm" className="mt-0.5">
                {t("linkedAs", {
                  id: link.external_id,
                  date: format.dateTime(new Date(link.linked_at), {
                    dateStyle: "medium",
                  }),
                })}
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
        ))}
        <SettingsRow
          tile={telegramTile}
          title={links.length ? t("linkAnother") : "Telegram"}
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
      </SettingsSection>
    </div>
  );
}
