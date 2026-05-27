import { createElement } from "react";
import {
  Clock,
  Github,
  Hash,
  Mail,
  MessageSquare,
  Send,
  Webhook,
  Zap,
  type LucideIcon,
} from "lucide-react";

export interface TriggerCatalogEntry {
  id?: string;
  name?: string;
  icon?: string;
  webhook_type?: string;
  data_extractor?: string;
}

export interface TriggerLike {
  trigger_type?: string;
  webhook_type?: string;
  data_extractor?: string;
  config?: {
    webhook_type?: string;
  } | null;
}

export function findTriggerCatalogEntry(
  trigger: TriggerLike,
  catalog: TriggerCatalogEntry[]
) {
  if (trigger.data_extractor) {
    const match = catalog.find(
      (entry) => entry.data_extractor === trigger.data_extractor
    );
    if (match) return match;
  }

  if (trigger.trigger_type === "cron") {
    return catalog.find((entry) => entry.id === "cron");
  }

  const webhookType = trigger.webhook_type || trigger.config?.webhook_type;
  return (
    catalog.find((entry) => entry.webhook_type === webhookType) ||
    catalog.find((entry) => entry.id === "webhook")
  );
}

function triggerIconKey(
  entry?: TriggerCatalogEntry | null,
  trigger?: TriggerLike
) {
  const webhookType = trigger?.webhook_type || trigger?.config?.webhook_type;
  return (
    entry?.id ||
    entry?.webhook_type ||
    webhookType ||
    trigger?.trigger_type ||
    "webhook"
  ).toLowerCase();
}

const TRIGGER_ICON_BY_KEY: Record<string, LucideIcon> = {
  cron: Clock,
  schedule: Clock,
  telegram: Send,
  slack: Hash,
  discord: MessageSquare,
  email: Mail,
  gmail: Mail,
  github: Github,
  webhook: Webhook,
  generic: Webhook,
  event: Zap,
};

export function getTriggerIconComponent(
  entry?: TriggerCatalogEntry | null,
  trigger?: TriggerLike
): LucideIcon {
  return TRIGGER_ICON_BY_KEY[triggerIconKey(entry, trigger)] ?? Webhook;
}

export function renderTriggerIcon(
  entry?: TriggerCatalogEntry | null,
  trigger?: TriggerLike,
  className = "h-5 w-5"
) {
  return createElement(getTriggerIconComponent(entry, trigger), { className });
}

export function getTriggerDisplayName(
  trigger: TriggerLike,
  entry?: TriggerCatalogEntry | null
) {
  return entry?.name ?? (trigger.trigger_type === "cron" ? "Cron" : "Webhook");
}
