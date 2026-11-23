import { TelegramIcon } from "@/components/brand-icons";
import { EntityAvatar } from "@/components/ui/entity-avatar";
import { deterministicHue } from "@/lib/avatar-hue";

/** A Telegram account's mark: the Telegram glyph on a graphite tile. */
export function TelegramTile({ size = 32 }: { size?: number }) {
  return (
    <EntityAvatar
      size={size}
      hue={deterministicHue("telegram")}
      iconScale={0.56}
      icon={<TelegramIcon className="text-foreground" />}
      aria-hidden
    />
  );
}
