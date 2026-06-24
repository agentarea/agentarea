"use client";

import {
  Bot,
  CheckCircle2,
  ScrollText,
  ShieldAlert,
  ShieldCheck,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import EmptyState from "@/components/EmptyState";
import {
  type InboxCounts,
  type FilterValue,
} from "@/app/(main)/inbox/components/inboxShared";

type EmptyStateButton = {
  label: string;
  href: string;
};

interface InboxEmptyStateProps {
  filter: FilterValue;
  counts: InboxCounts;
}

export function InboxEmptyState({ filter, counts }: InboxEmptyStateProps) {
  const copy: Record<
    FilterValue,
    {
      title: string;
      description: string;
      icons: LucideIcon[];
      buttons: EmptyStateButton[];
    }
  > = {
    all: {
      title: "No inbox decisions yet",
      description:
        "When an agent needs approval, completes a governed action, or fails a controlled step, it will appear here for review.",
      icons: [Bot, ShieldCheck, ScrollText],
      buttons: [
        { label: "Open task history", href: "/tasks" },
        { label: "Check triggers", href: "/triggers" },
      ],
    },
    pending: {
      title: "Approval queue is clear",
      description:
        "No agent is waiting on a human decision right now. New escalations will land here before they can continue.",
      icons: [Bot, ShieldAlert, ScrollText],
      buttons: [
        ...(counts.all > 0 ? [{ label: "View all", href: "/inbox" }] : []),
        { label: "Open task history", href: "/tasks" },
        { label: "Check triggers", href: "/triggers" },
      ],
    },
    completed: {
      title: "No completed approvals",
      description:
        "Approved actions will appear here after operators release them, so you can audit what moved forward.",
      icons: [CheckCircle2, ShieldCheck, ScrollText],
      buttons: [
        ...(counts.all > 0 ? [{ label: "View all", href: "/inbox" }] : []),
        { label: "Open task history", href: "/tasks" },
        { label: "Check triggers", href: "/triggers" },
      ],
    },
    failed: {
      title: "No rejected or failed approvals",
      description:
        "Rejected actions and failed escalations will appear here when a governed path is stopped.",
      icons: [XCircle, ShieldAlert, ScrollText],
      buttons: [
        ...(counts.all > 0 ? [{ label: "View all", href: "/inbox" }] : []),
        { label: "Open task history", href: "/tasks" },
        { label: "Check triggers", href: "/triggers" },
      ],
    },
  };
  const { title, description, icons, buttons } = copy[filter];
  const [action, additionAction, tertiaryAction] = buttons;

  return (
    <div className="flex h-full justify-center px-6 py-10">п
      <div className="flex w-full flex-col gap-3">
        <EmptyState
          title={title}
          description={description}
          icons={icons}
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
