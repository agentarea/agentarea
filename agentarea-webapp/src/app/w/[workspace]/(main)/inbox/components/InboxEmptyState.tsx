"use client";

import { useTranslations } from "next-intl";
import {
  Bot,
  CheckCircle2,
  MessageCircleQuestion,
  ScrollText,
  ShieldAlert,
  ShieldCheck,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import {
  type FilterValue,
  type InboxCounts,
} from "@/app/w/[workspace]/(main)/inbox/components/inboxShared";
import EmptyState from "@/components/EmptyState";

type EmptyStateButton = {
  label: string;
  href: string;
};

interface InboxEmptyStateProps {
  filter: FilterValue;
  counts: InboxCounts;
}

const ICONS: Record<FilterValue, LucideIcon[]> = {
  all: [Bot, ShieldCheck, ScrollText],
  pending: [Bot, ShieldAlert, ScrollText],
  input: [Bot, MessageCircleQuestion, ScrollText],
  completed: [CheckCircle2, ShieldCheck, ScrollText],
  failed: [XCircle, ShieldAlert, ScrollText],
};

export function InboxEmptyState({ filter, counts }: InboxEmptyStateProps) {
  const t = useTranslations("InboxPage.emptyList");

  const taskHistory = { label: t("taskHistory"), href: "/tasks" };
  const triggers = { label: t("triggers"), href: "/triggers" };
  const buttons: EmptyStateButton[] =
    filter === "all"
      ? [taskHistory, triggers]
      : [
          ...(counts.all > 0 ? [{ label: t("viewAll"), href: "/inbox" }] : []),
          taskHistory,
          triggers,
        ];
  const [action, additionAction, tertiaryAction] = buttons;

  return (
    <div className="flex h-full justify-center px-6 py-10">
      <div className="flex w-full flex-col gap-3">
        <EmptyState
          title={t(`${filter}.title`)}
          description={t(`${filter}.description`)}
          icons={ICONS[filter]}
          action={toEmptyStateAction(tertiaryAction ?? action)}
          additionAction={toEmptyStateAction(additionAction)}
        />
      </div>
    </div>
  );
}

function toEmptyStateAction(button?: EmptyStateButton) {
  return button
    ? {
        label: button.label,
        href: button.href,
      }
    : undefined;
}
