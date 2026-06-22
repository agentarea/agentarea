"use client";

import { useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowLeft,
  Bot,
  Calendar,
  Clock,
  Code2,
  Globe,
  Hash,
  Info,
  List,
  Mail,
  MessageSquare,
  Plug,
  Send,
  Tag,
  Webhook,
  Zap,
  type LucideIcon,
} from "lucide-react";
import ContentBlock from "@/components/ContentBlock";
import FormLabel from "@/components/FormLabel/FormLabel";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusIndicator } from "@/components/ui/status-indicator";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

type Source = "schedule" | "event" | "channel" | null;

export default function NewTriggerPage() {
  const [source, setSource] = useState<Source>(null);

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: "Triggers", href: "/triggers" },
          { label: source ? "Configure" : "New trigger" },
        ],
        backLink: { label: "Back", href: "/triggers" },
      }}
    >
      <div className="form-content lg:max-w-xl lg:mx-auto py-5">
        {!source && <SourcePicker onPick={setSource} />}
        {source === "schedule" && (
          <ScheduleForm onBack={() => setSource(null)} />
        )}
        {source === "event" && <EventForm onBack={() => setSource(null)} />}
        {source === "channel" && (
          <ChannelForm onBack={() => setSource(null)} />
        )}
      </div>
    </ContentBlock>
  );
}

function SourcePicker({ onPick }: { onPick: (s: Source) => void }) {
  const sources: Array<{
    id: NonNullable<Source>;
    icon: LucideIcon;
    name: string;
    description: string;
    examples: string;
  }> = [
    {
      id: "schedule",
      icon: Clock,
      name: "On a schedule",
      description: "Cron expression — fires on a recurring timer.",
      examples: "Every 5 min · Daily at 09:00 · Weekdays only",
    },
    {
      id: "event",
      icon: Zap,
      name: "On an event",
      description: "A webhook URL or system event fires once when it happens.",
      examples: "GitHub PR opened · Generic webhook · System events",
    },
    {
      id: "channel",
      icon: Plug,
      name: "From a channel",
      description:
        "A message arrives in a connected channel — Slack, Telegram, email, chat, A2A.",
      examples: "Mention in #ops · DM to bot · Reply to thread",
    },
  ];

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold">What should fire this trigger?</h2>
        <p className="text-sm text-muted-foreground">
          Pick a source. Each one has a focused form on the next step.
        </p>
      </div>

      <div className="grid gap-3">
        {sources.map((s) => {
          const Icon = s.icon;
          return (
            <button
              key={s.id}
              type="button"
              onClick={() => onPick(s.id)}
              className={cn(
                "flex items-start gap-3 rounded-lg border border-border bg-card p-4 text-left transition-colors",
                "hover:border-primary/50 hover:bg-muted/40"
              )}
            >
              <div className="rounded-md bg-primary/10 p-2">
                <Icon className="h-4 w-4 text-primary" strokeWidth={1.5} />
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">{s.name}</p>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {s.description}
                </p>
                <p className="mt-1.5 text-xs text-muted-foreground/70">
                  {s.examples}
                </p>
              </div>
            </button>
          );
        })}
      </div>

      <p className="text-xs text-muted-foreground">
        Don&apos;t see the source you want? Connections live under{" "}
        <Link href="/channels" className="small-link inline-flex">
          Channels
        </Link>
        .
      </p>
    </div>
  );
}

function StepHeader({
  title,
  subtitle,
  onBack,
}: {
  title: string;
  subtitle: string;
  onBack: () => void;
}) {
  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={onBack}
        className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        Change source
      </button>
      <div>
        <h2 className="text-lg font-semibold">{title}</h2>
        <p className="text-sm text-muted-foreground">{subtitle}</p>
      </div>
    </div>
  );
}

function CommonFields() {
  return (
    <>
      <div className="grid gap-2">
        <FormLabel htmlFor="name" icon={Tag} required>
          Name
        </FormLabel>
        <Input id="name" name="name" placeholder="e.g. Daily summary" />
      </div>

      <div className="grid gap-2">
        <FormLabel htmlFor="agent_id" icon={Bot} required>
          Agent
        </FormLabel>
        <Select name="agent_id">
          <SelectTrigger id="agent_id">
            <SelectValue placeholder="Select agent…" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="a1">Research Agent</SelectItem>
            <SelectItem value="a2">Ops Agent</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="grid gap-2">
        <FormLabel htmlFor="task_parameters" icon={Code2} optional>
          Task parameters
        </FormLabel>
        <Textarea
          id="task_parameters"
          name="task_parameters"
          placeholder='{"topic": "weekly recap"}'
          className="font-mono min-h-[100px]"
        />
      </div>

      <div className="grid gap-2">
        <FormLabel htmlFor="failure_threshold" icon={AlertTriangle} optional>
          Failure threshold
        </FormLabel>
        <Input
          id="failure_threshold"
          name="failure_threshold"
          type="number"
          min={1}
          placeholder="e.g. 3"
        />
      </div>
    </>
  );
}

function FormFooter({
  onBack,
  ctaLabel,
}: {
  onBack: () => void;
  ctaLabel: string;
}) {
  return (
    <div className="flex justify-end gap-2 pt-2">
      <Button type="button" variant="outline" onClick={onBack}>
        Cancel
      </Button>
      <Button type="button">{ctaLabel}</Button>
    </div>
  );
}

function ScheduleForm({ onBack }: { onBack: () => void }) {
  return (
    <div className="space-y-6">
      <StepHeader
        title="Schedule"
        subtitle="Fires on a cron expression. No external connection needed."
        onBack={onBack}
      />

      <div className="space-y-4">
        <div className="grid gap-2">
          <FormLabel htmlFor="cron_expression" icon={Calendar} required>
            Cron expression
          </FormLabel>
          <div className="flex gap-2">
            <Input
              id="cron_expression"
              name="cron_expression"
              defaultValue="0 9 * * 1-5"
              className="font-mono"
            />
            <Select name="timezone" defaultValue="UTC">
              <SelectTrigger className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="UTC">UTC</SelectItem>
                <SelectItem value="America/New_York">
                  America/New_York
                </SelectItem>
                <SelectItem value="Europe/London">Europe/London</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <p className="text-xs text-muted-foreground">
            Next run: <span className="tabular-nums">Mon 09:00 UTC</span> · 5
            fires this week
          </p>
        </div>

        <CommonFields />
      </div>

      <FormFooter onBack={onBack} ctaLabel="Create schedule" />
    </div>
  );
}

function EventForm({ onBack }: { onBack: () => void }) {
  const [eventType, setEventType] = useState<string>("webhook");

  const events: Array<{
    id: string;
    name: string;
    icon: LucideIcon;
    hint: string;
  }> = [
    {
      id: "webhook",
      name: "Generic webhook",
      icon: Webhook,
      hint: "Any HTTP source",
    },
    {
      id: "github",
      name: "GitHub",
      icon: Globe,
      hint: "PR · Issue · Push",
    },
    {
      id: "system",
      name: "System event",
      icon: Bot,
      hint: "Workspace internal",
    },
  ];

  return (
    <div className="space-y-6">
      <StepHeader
        title="Event"
        subtitle="Fires once when an external system emits the event."
        onBack={onBack}
      />

      <div className="space-y-4">
        <div className="grid gap-2">
          <FormLabel icon={List} required>
            Event source
          </FormLabel>
          <div className="grid grid-cols-3 gap-2">
            {events.map((e) => {
              const Icon = e.icon;
              const sel = eventType === e.id;
              return (
                <button
                  key={e.id}
                  type="button"
                  onClick={() => setEventType(e.id)}
                  className={cn(
                    "flex flex-col items-start gap-1.5 rounded-lg border p-3 text-left transition-colors",
                    sel
                      ? "border-primary bg-primary/5"
                      : "border-border hover:border-primary/50 hover:bg-muted/40"
                  )}
                >
                  <Icon
                    className={cn(
                      "h-4 w-4",
                      sel ? "text-primary" : "text-muted-foreground"
                    )}
                  />
                  <span className="text-sm font-medium">{e.name}</span>
                  <span className="text-xs text-muted-foreground">{e.hint}</span>
                </button>
              );
            })}
          </div>
        </div>

        {eventType === "webhook" && (
          <div className="rounded-lg border border-border/60 bg-muted/20 p-3 space-y-1.5">
            <div className="flex items-start gap-2">
              <Info className="h-4 w-4 text-muted-foreground mt-0.5 shrink-0" />
              <div className="space-y-1">
                <p className="text-sm font-medium">Webhook endpoint</p>
                <p className="text-xs text-muted-foreground">
                  A unique URL is generated after you create this trigger. Copy
                  it from the trigger detail page and paste it into your source.
                </p>
              </div>
            </div>
          </div>
        )}

        <CommonFields />
      </div>

      <FormFooter onBack={onBack} ctaLabel="Create event trigger" />
    </div>
  );
}

function ChannelForm({ onBack }: { onBack: () => void }) {
  const channels = [
    {
      id: "c1",
      name: "Slack · Acme workspace",
      icon: Hash,
      status: "Connected",
    },
    { id: "c2", name: "Telegram · @ops_bot", icon: Send, status: "Connected" },
    { id: "c3", name: "Email · ops@acme.dev", icon: Mail, status: "Connected" },
  ];
  const [selected, setSelected] = useState<string>(channels[0].id);
  const triggers = ["mention", "DM", "any message", "reaction"];
  const [activeTriggers, setActiveTriggers] = useState<string[]>(["mention"]);

  const toggle = (t: string) =>
    setActiveTriggers((prev) =>
      prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]
    );

  return (
    <div className="space-y-6">
      <StepHeader
        title="Channel"
        subtitle="Fires on inbound messages from a connected channel."
        onBack={onBack}
      />

      <div className="space-y-4">
        <div className="grid gap-2">
          <FormLabel icon={Plug} required>
            Channel
          </FormLabel>
          <div className="rounded-lg border border-border bg-card divide-y divide-border">
            {channels.map((c) => {
              const Icon = c.icon;
              const sel = selected === c.id;
              return (
                <button
                  key={c.id}
                  type="button"
                  onClick={() => setSelected(c.id)}
                  className={cn(
                    "flex w-full items-center gap-3 px-3 py-2.5 text-left transition-colors",
                    sel ? "bg-primary/5" : "hover:bg-muted/40"
                  )}
                >
                  <Icon
                    className={cn(
                      "h-4 w-4",
                      sel ? "text-primary" : "text-muted-foreground"
                    )}
                  />
                  <span className="flex-1 text-sm font-medium">{c.name}</span>
                  <StatusIndicator size="sm" tone="success" className="whitespace-nowrap">
                    {c.status}
                  </StatusIndicator>
                </button>
              );
            })}
          </div>
          <Link
            href="/channels/new"
            className="small-link inline-flex text-xs"
          >
            + Connect a new channel
          </Link>
        </div>

        <div className="grid gap-2">
          <FormLabel icon={MessageSquare}>Trigger when</FormLabel>
          <div className="flex flex-wrap gap-2">
            {triggers.map((t) => {
              const sel = activeTriggers.includes(t);
              return (
                <button
                  key={t}
                  type="button"
                  onClick={() => toggle(t)}
                  className={cn(
                    "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors",
                    sel
                      ? "bg-primary text-primary-foreground"
                      : "bg-muted text-muted-foreground hover:bg-muted/80"
                  )}
                >
                  {t}
                </button>
              );
            })}
          </div>
        </div>

        <CommonFields />
      </div>

      <FormFooter onBack={onBack} ctaLabel="Create channel trigger" />
    </div>
  );
}
