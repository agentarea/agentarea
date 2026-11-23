import type { ReactNode } from "react";
import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";
import { AuthLayout } from "@/components/auth/auth-layout";
import { FocusCard, FocusHeader, FocusStep } from "@/components/FocusCard";
import { TelegramTile } from "@/components/TelegramTile";
import { previewTelegramLinkOffer } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";
import { displayName, type NameTraits } from "@/lib/display-name";
import { getServerSession } from "@/lib/ory";
import { telegramAccountLabel } from "@/lib/telegram-account";
import { getPersonalWorkspacePath } from "@/lib/workspace-context";
import LinkTelegramConfirm from "./LinkTelegramConfirm";

/**
 * Where a bot sends someone it does not recognise. Its link carries a code
 * that names their Telegram account, so the signed-in person confirms once
 * here and the account is theirs. A link without a code (an older bot reply)
 * lands in the personal workspace's settings, which link through the bot.
 */
export default async function LinkTelegramPage({
  searchParams,
}: {
  searchParams: Promise<{ bot?: string; code?: string }>;
}) {
  const { bot, code } = await searchParams;
  if (!code) {
    const query = bot ? `?link_telegram=${encodeURIComponent(bot)}` : "";
    redirect(await getPersonalWorkspacePath(`/settings${query}#messengers`));
  }

  const t = await getTranslations("LinkTelegram");
  const [offer, session, settingsHref] = await Promise.all([
    previewTelegramLinkOffer(code),
    getServerSession(),
    getPersonalWorkspacePath("/settings#messengers"),
  ]);
  const botName = offer.data?.bot ?? bot;
  const botLabel = botName ? `@${botName}` : t("theBot");

  if (!offer.data) {
    return (
      <LinkCard title={t("titleUnknown")} subtitle={t("subtitleUnknown")}>
        {offer.status === 404 ? (
          <FocusStep
            kind="off"
            title={t("goneTitle")}
            detail={t("goneDetail", { bot: botLabel })}
          />
        ) : (
          <FocusStep
            kind="failed"
            title={t("failed")}
            detail={apiErrorMessage(offer, t("failed"))}
          />
        )}
      </LinkCard>
    );
  }

  const account = telegramAccountLabel(offer.data);
  const traits = session?.identity?.traits as NameTraits | undefined;
  const you = traits?.email || displayName(traits);

  return (
    <LinkCard
      title={t("title", { account })}
      subtitle={you ? t("subtitle", { you }) : t("subtitleUnknown")}
    >
      {offer.data.linked_to === "you" ? (
        <FocusStep
          kind="done"
          title={t("alreadyYoursTitle")}
          detail={t("linkedDetail", { bot: botLabel })}
        />
      ) : offer.data.linked_to === "another_account" ? (
        <FocusStep
          kind="attention"
          title={t("takenTitle")}
          detail={t("takenDetail")}
        />
      ) : (
        <LinkTelegramConfirm
          code={code}
          bot={botName ? botLabel : ""}
          settingsHref={settingsHref}
        />
      )}
    </LinkCard>
  );
}

function LinkCard({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
}) {
  return (
    <AuthLayout>
      <FocusCard>
        <FocusHeader
          mark={<TelegramTile size={48} />}
          title={title}
          subtitle={subtitle}
        />
        {children}
      </FocusCard>
    </AuthLayout>
  );
}
