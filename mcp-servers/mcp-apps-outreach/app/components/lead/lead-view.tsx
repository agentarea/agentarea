import type { LeadCard, LeadStep } from "@shared/schema";
import {
  Building2,
  CalendarCheck,
  Check,
  Circle,
  CircleSlash,
  Clock,
  Eye,
  Lightbulb,
  Loader2,
  type LucideIcon,
  Mail,
  MapPin,
  MessageSquareReply,
  MousePointerClick,
  Plus,
  RefreshCw,
  Send,
  Users,
} from "lucide-react";
import type { ReactNode } from "react";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { formatCurrency, formatDate, formatDateTime, formatNumber, initials, timeAgo, timeUntil } from "@/lib/format";
import { REPLY_META, SIGNAL_META, STATUS_META, STRENGTH_META } from "@/lib/meta";
import { cn } from "@/lib/utils";
import { ReplyClassBadge } from "../reply-class-badge";
import { ThreadMessage } from "../thread-message";

type Busy = "add" | "handle" | "refresh" | null;

const STEP_META: Record<LeadStep["state"], { label: string; icon: LucideIcon; tone: string }> = {
  replied: { label: "Replied", icon: MessageSquareReply, tone: "bg-success-surface text-success border-transparent" },
  clicked: { label: "Clicked", icon: MousePointerClick, tone: "bg-info-surface text-info border-transparent" },
  opened: { label: "Opened", icon: Eye, tone: "bg-info-surface text-info border-transparent" },
  sent: { label: "Sent, not opened", icon: Send, tone: "bg-secondary text-muted-foreground border-transparent" },
  scheduled: { label: "Scheduled", icon: Clock, tone: "bg-background text-info border-info/50 border-dashed" },
  skipped: { label: "Skipped — they replied", icon: CircleSlash, tone: "bg-background text-subtle-foreground" },
  not_started: { label: "Not started", icon: Circle, tone: "bg-background text-subtle-foreground" },
};

function SectionLabel({ children }: { children: ReactNode }) {
  return <h3 className="text-subtle-foreground mb-2 text-[10px] font-semibold tracking-wider uppercase">{children}</h3>;
}

function Header({
  card,
  busy,
  onAddToSequence,
  onMarkHandled,
  onRefresh,
}: {
  card: LeadCard;
  busy: Busy;
  onAddToSequence: (anchor: HTMLElement) => void;
  onMarkHandled: (anchor: HTMLElement) => void;
  onRefresh: (anchor: HTMLElement) => void;
}) {
  const { contact, account, enrollment, reply, meeting, targetCampaign } = card;
  const status = enrollment ? STATUS_META[enrollment.status] : { label: "Not in a sequence", variant: "muted" as const };
  const accent = reply ? REPLY_META[reply.classification].color : "var(--info)";

  return (
    <Card className="relative gap-0 overflow-hidden py-0">
      {/* A thin band in the lead's current colour: reply class if they answered, otherwise info. */}
      <div className="h-1 w-full" style={{ background: accent }} aria-hidden />
      <div className="flex flex-wrap items-start gap-4 p-4 sm:p-5">
        <Avatar className="size-14 rounded-xl">
          <AvatarFallback
            className="rounded-xl text-lg font-semibold"
            style={{ background: `color-mix(in oklab, ${accent} 14%, var(--muted))`, color: accent }}
          >
            {initials(contact.name)}
          </AvatarFallback>
        </Avatar>

        <div className="min-w-0 flex-1">
          <h1 className="truncate text-lg leading-tight font-semibold tracking-tight">{contact.name}</h1>
          <p className="text-muted-foreground mt-0.5 truncate text-sm">
            {contact.title} at <span className="text-foreground font-medium">{account.name}</span>
          </p>
          <p className="text-subtle-foreground mt-1 flex items-center gap-1.5 truncate font-mono text-xs">
            <Mail className="size-3" />
            {contact.email}
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            <Badge variant={status.variant}>{status.label}</Badge>
            {enrollment && <Badge variant="outline">{enrollment.campaign.name}</Badge>}
            {reply && <ReplyClassBadge classification={reply.classification} />}
            {reply && !reply.handled && <Badge variant="danger">Needs handling</Badge>}
            {meeting && (
              <Badge variant="success">
                <CalendarCheck />
                {formatDateTime(meeting.scheduledFor)} · {formatCurrency(meeting.pipelineValue)}
              </Badge>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="outline"
                size="icon"
                className="size-8"
                aria-label="Refresh"
                disabled={busy !== null}
                onClick={(event) => onRefresh(event.currentTarget)}
              >
                <RefreshCw className={cn(busy === "refresh" && "animate-spin")} />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Reload from the MCP server</TooltipContent>
          </Tooltip>
          {!enrollment && targetCampaign && (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button size="sm" disabled={busy !== null} onClick={(event) => onAddToSequence(event.currentTarget)}>
                  {busy === "add" ? <Loader2 className="animate-spin" /> : <Plus />}
                  Add to sequence
                </Button>
              </TooltipTrigger>
              <TooltipContent>Enroll in “{targetCampaign.name}”; step 1 is scheduled</TooltipContent>
            </Tooltip>
          )}
          {reply && (
            <Button
              size="sm"
              variant={reply.handled ? "outline" : "default"}
              disabled={reply.handled || busy !== null}
              onClick={(event) => onMarkHandled(event.currentTarget)}
            >
              {busy === "handle" ? <Loader2 className="animate-spin" /> : <Check />}
              {reply.handled ? "Handled" : "Mark handled"}
            </Button>
          )}
        </div>
      </div>
    </Card>
  );
}

function NextStep({ card }: { card: LeadCard }) {
  return (
    <div className="bg-info-surface border-info/20 flex gap-3 rounded-xl border p-4">
      <span className="bg-info/15 text-info flex size-8 shrink-0 items-center justify-center rounded-lg">
        <Lightbulb className="size-4" />
      </span>
      <div>
        <p className="text-info text-[10px] font-semibold tracking-wider uppercase">Suggested next step</p>
        <p className="mt-1 text-sm leading-relaxed">{card.suggestedNextStep}</p>
      </div>
    </div>
  );
}

function Sequence({ card }: { card: LeadCard }) {
  const { enrollment, targetCampaign, steps } = card;
  const campaign = enrollment?.campaign ?? targetCampaign;
  return (
    <Card className="gap-3">
      <CardHeader>
        <CardTitle>Sequence</CardTitle>
        <CardDescription>
          {enrollment
            ? `${campaign?.name} · step ${enrollment.step} of ${enrollment.totalSteps} sent`
            : campaign
              ? `Would run “${campaign.name}”`
              : "No campaign fits this lead yet"}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {steps.length === 0 ? (
          <p className="text-muted-foreground text-xs">Nothing to show until a signal routes this lead to a campaign.</p>
        ) : (
          <ol className="relative flex flex-col gap-3">
            {steps.map((step, index) => {
              const meta = STEP_META[step.state];
              const Icon = meta.icon;
              const last = index === steps.length - 1;
              return (
                <li key={step.step} className="relative grid grid-cols-[28px_1fr] gap-3">
                  {!last && <span className="bg-border absolute top-8 bottom-[-12px] left-[13.5px] w-px" aria-hidden />}
                  <span className={cn("z-10 flex size-7 items-center justify-center rounded-full border", meta.tone)}>
                    <Icon className="size-3.5" />
                  </span>
                  <div className="min-w-0 pt-0.5">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-semibold">Step {step.step}</span>
                      <span className="text-muted-foreground text-[11px]">{meta.label}</span>
                    </div>
                    <p className="mt-0.5 truncate text-[13px]">{step.subject}</p>
                    <p className="text-subtle-foreground tabular mt-0.5 text-[11px]">
                      {step.sentAt
                        ? [
                            `sent ${formatDate(step.sentAt)}`,
                            step.openedAt && `opened ${timeAgo(step.openedAt, card.asOf)}`,
                            step.clickedAt && "link clicked",
                          ]
                            .filter(Boolean)
                            .join(" · ")
                        : step.dueAt
                          ? `due ${formatDate(step.dueAt)} (${timeUntil(step.dueAt, card.asOf)})`
                          : "—"}
                    </p>
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}

function Signals({ card }: { card: LeadCard }) {
  const { signal, accountSignals } = card;
  return (
    <Card className="gap-3">
      <CardHeader>
        <CardTitle>Buying signal</CardTitle>
        <CardDescription>{card.enrollment ? "What triggered the outreach" : "Newest signal on this lead"}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {signal ? (
          (() => {
            const meta = SIGNAL_META[signal.type];
            const strength = STRENGTH_META[signal.strength];
            const Icon = meta.icon;
            const StrengthIcon = strength.icon;
            return (
              <div className="flex items-start gap-3 rounded-lg border p-3">
                <span className={cn("flex size-9 shrink-0 items-center justify-center rounded-lg", meta.tile)}>
                  <Icon className="size-4" />
                </span>
                <div className="min-w-0">
                  <p className="text-sm leading-snug font-medium">{signal.description}</p>
                  <div className="text-muted-foreground mt-1.5 flex flex-wrap items-center gap-1.5 text-xs">
                    <Badge variant={strength.variant}>
                      <StrengthIcon />
                      {strength.label}
                    </Badge>
                    {meta.label} · {timeAgo(signal.detectedAt, card.asOf)}
                  </div>
                </div>
              </div>
            );
          })()
        ) : (
          <p className="text-muted-foreground text-xs">No signal on record for this person.</p>
        )}
        {accountSignals.length > 0 && (
          <div>
            <SectionLabel>Also at {card.account.name}</SectionLabel>
            <ul className="flex flex-col gap-2">
              {accountSignals.map((s) => {
                const meta = SIGNAL_META[s.type];
                const Icon = meta.icon;
                return (
                  <li key={s.id} className="flex items-center gap-2 text-xs">
                    <span className={cn("flex size-5 shrink-0 items-center justify-center rounded", meta.tile)}>
                      <Icon className="size-3" />
                    </span>
                    <span className="min-w-0 flex-1 truncate">{s.description}</span>
                    <span className="text-subtle-foreground tabular shrink-0">{timeAgo(s.detectedAt, card.asOf)}</span>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Company({ card }: { card: LeadCard }) {
  const { account } = card;
  const rows: [LucideIcon, string, string][] = [
    [Building2, "Industry", account.industry],
    [Users, "Employees", formatNumber(account.employees)],
    [MapPin, "HQ", `${account.hq} · ${account.region}`],
  ];
  return (
    <Card className="gap-3">
      <CardHeader>
        <CardTitle>{account.name}</CardTitle>
        <CardDescription className="font-mono">{account.domain}</CardDescription>
      </CardHeader>
      <CardContent>
        <dl className="grid gap-2">
          {rows.map(([Icon, label, value]) => (
            <div key={label} className="flex items-center gap-2 text-xs">
              <Icon className="text-subtle-foreground size-3.5 shrink-0" />
              <dt className="text-muted-foreground w-20 shrink-0">{label}</dt>
              <dd className="min-w-0 truncate font-medium">{value}</dd>
            </div>
          ))}
        </dl>
      </CardContent>
    </Card>
  );
}

function Thread({ card }: { card: LeadCard }) {
  const accent = card.reply ? REPLY_META[card.reply.classification].color : "var(--border)";
  return (
    <Card className="gap-3">
      <CardHeader>
        <CardTitle>Thread</CardTitle>
        <CardDescription>
          {card.thread.length === 0
            ? "Nothing sent yet"
            : `${card.thread.length} ${card.thread.length === 1 ? "message" : "messages"}`}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {card.thread.length === 0 ? (
          <p className="text-muted-foreground rounded-lg border border-dashed px-4 py-10 text-center text-sm">
            {card.enrollment ? "Step 1 hasn't gone out yet." : `No emails to ${card.contact.firstName} yet.`}
          </p>
        ) : (
          <ol className="before:bg-border relative flex flex-col gap-5 before:absolute before:top-2 before:bottom-2 before:left-[4.5px] before:w-px">
            {card.thread.map((message, index) => (
              <ThreadMessage key={index} message={message} accent={accent} />
            ))}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}

export function LeadView(props: {
  card: LeadCard;
  busy: Busy;
  onAddToSequence: (anchor: HTMLElement) => void;
  onMarkHandled: (anchor: HTMLElement) => void;
  onRefresh: (anchor: HTMLElement) => void;
}) {
  const { card, busy } = props;
  return (
    <div
      className="flex flex-col gap-4 transition-opacity data-[busy=true]:opacity-70"
      data-busy={busy === "add" || busy === "handle"}
    >
      <Header {...props} />
      {/* Narrow: next step, then the facts, then the thread. Wide: facts in a side column. */}
      <div className="grid gap-4 lg:grid-cols-12 lg:grid-rows-[auto_1fr]">
        <div className="lg:col-span-8">
          <NextStep card={card} />
        </div>
        <aside className="flex flex-col gap-4 lg:col-span-4 lg:row-span-2">
          <Sequence card={card} />
          <Signals card={card} />
          <Company card={card} />
        </aside>
        <div className="lg:col-span-8">
          <Thread card={card} />
        </div>
      </div>
    </div>
  );
}

export function LeadSkeleton() {
  return (
    <div className="flex flex-col gap-4" aria-busy="true" aria-label="Loading lead">
      <Card className="flex-row items-center gap-4 p-5">
        <Skeleton className="size-14 rounded-xl" />
        <div className="flex flex-1 flex-col gap-2">
          <Skeleton className="h-5 w-48" />
          <Skeleton className="h-3.5 w-72" />
          <Skeleton className="h-3 w-40" />
        </div>
      </Card>
      <div className="grid gap-4 lg:grid-cols-12">
        <div className="flex flex-col gap-4 lg:col-span-8">
          <Skeleton className="h-20 rounded-xl" />
          <Skeleton className="h-[420px] rounded-xl" />
        </div>
        <div className="flex flex-col gap-4 lg:col-span-4">
          <Skeleton className="h-56 rounded-xl" />
          <Skeleton className="h-44 rounded-xl" />
        </div>
      </div>
    </div>
  );
}
