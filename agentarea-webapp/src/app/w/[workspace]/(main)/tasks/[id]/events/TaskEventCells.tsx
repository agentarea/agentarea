"use client";

import { useCallback, type ReactNode } from "react";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import {
  Activity,
  Braces,
  Coins,
  Cpu,
  Flag,
  Hash,
  Layers,
  LayoutTemplate,
  MessageSquareText,
  MessagesSquare,
  Package,
  Repeat,
  Server,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
  Wallet,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { EntityAvatar } from "@/components/ui/entity-avatar";
import { useCurrency } from "@/hooks/useCurrency";
import { deterministicHue } from "@/lib/avatar-hue";
import { formatMoney } from "@/lib/money";
import type { DisplayEvent } from "@/types/events";
import {
  eventCategory,
  eventFacts,
  eventSummary,
  eventTypeKey,
  splitEventType,
  type EventCategory,
  type EventFact,
} from "./taskEventDisplay";

const CATEGORY_ICONS: Record<EventCategory, LucideIcon> = {
  task: Flag,
  iteration: Repeat,
  llm: Sparkles,
  tool: Wrench,
  input: MessageSquareText,
  approval: ShieldCheck,
  artifact: Package,
  ui: LayoutTemplate,
  budget: Wallet,
  context: Layers,
  runtime: Server,
  other: Activity,
};

/** The name a known event type reads as, in the UI language. */
export function useEventLabel() {
  const t = useTranslations("TaskEventsPage.types");
  return useCallback(
    (type: string) => {
      const key = eventTypeKey(type);
      return key ? t(key) : null;
    },
    [t]
  );
}

/**
 * What the event is: its category's tile, then its name. A type the UI knows
 * reads as words, the type as sent kept in the tooltip; an unknown one shows
 * as sent, with the scope that repeats down the table quieted.
 */
export function EventTypeCell({ type }: { type: string }) {
  const labelOf = useEventLabel();
  const category = eventCategory(type);
  const Icon = CATEGORY_ICONS[category];
  const label = labelOf(type);
  const { scope, action } = splitEventType(type);

  return (
    <span className="flex min-w-0 items-center gap-2" title={type}>
      <EntityAvatar
        size={20}
        hue={deterministicHue(category)}
        icon={<Icon strokeWidth={1.85} />}
        aria-hidden
      />
      {label ? (
        <span className="line-clamp-2 min-w-0 break-words text-[13px] font-medium">
          {label}
        </span>
      ) : (
        <code className="min-w-0 truncate font-mono text-xs">
          {scope && <span className="text-muted-foreground">{scope}</span>}
          {action}
        </code>
      )}
    </span>
  );
}

function Fact({
  icon: Icon,
  title,
  children,
}: {
  icon: LucideIcon;
  title: string;
  children: ReactNode;
}) {
  return (
    <span className="inline-flex min-w-0 items-center gap-1" title={title}>
      <Icon className="h-3 w-3 shrink-0" aria-hidden />
      <span className="truncate">{children}</span>
    </span>
  );
}

function EventFactItem({ fact }: { fact: EventFact }) {
  const t = useTranslations("TaskEventsPage.facts");
  const format = useFormatter();
  const locale = useLocale();
  const { currency } = useCurrency();

  switch (fact.kind) {
    case "tool":
      return (
        <Fact icon={Wrench} title={t("tool")}>
          <span className="font-mono">{fact.value}</span>
        </Fact>
      );
    case "arguments":
      return (
        <Fact icon={Braces} title={t("arguments")}>
          <span className="font-mono">{fact.value.join(", ")}</span>
        </Fact>
      );
    case "model":
      return (
        <Fact icon={Cpu} title={t("model")}>
          {fact.value}
        </Fact>
      );
    case "iteration":
      return (
        <Fact icon={Repeat} title={t("iteration", { n: fact.value })}>
          {t("iteration", { n: fact.value })}
        </Fact>
      );
    case "messages":
      return (
        <Fact icon={MessagesSquare} title={t("messages", { count: fact.value })}>
          {t("messages", { count: fact.value })}
        </Fact>
      );
    case "tokens":
      return (
        <Fact icon={Hash} title={t("tokens")}>
          <span className="tabular-nums">
            {format.number(fact.input)} → {format.number(fact.output)}
          </span>
        </Fact>
      );
    case "cost":
      return (
        <Fact icon={Coins} title={t("cost")}>
          <span className="tabular-nums">
            {formatMoney(fact.value, currency, locale)}
          </span>
        </Fact>
      );
    case "errorType":
      return (
        <Fact icon={TriangleAlert} title={t("errorType")}>
          <span className="font-mono">{fact.value}</span>
        </Fact>
      );
  }
}

/**
 * What happened: the event's own words, then the facts its data carries —
 * the tool, the model, the iteration, tokens and cost — so a row says enough
 * without being opened. A row with neither reads as a dash.
 */
export function EventDescriptionCell({
  event,
  children,
}: {
  event: DisplayEvent;
  /** Below everything, e.g. the opened data. */
  children?: ReactNode;
}) {
  const summary = eventSummary(event.data);
  const facts = eventFacts(event.data);

  return (
    <div className="min-w-0 space-y-1">
      {summary ? (
        <p className="line-clamp-2 break-words text-[13px] text-foreground">
          {summary}
        </p>
      ) : (
        facts.length === 0 && <span className="text-muted-foreground">—</span>
      )}
      {facts.length > 0 && (
        <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
          {facts.map((fact) => (
            <EventFactItem key={fact.kind} fact={fact} />
          ))}
        </div>
      )}
      {children}
    </div>
  );
}
