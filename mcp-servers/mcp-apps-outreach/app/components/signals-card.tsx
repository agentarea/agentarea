import type { SignalRow, Snapshot } from "@shared/schema";
import { Check, Plus } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { formatNumber, timeAgo } from "@/lib/format";
import { SIGNAL_META, STRENGTH_META } from "@/lib/meta";
import { cn } from "@/lib/utils";

type View = "all" | "action";

function SignalItem({
  signal,
  asOf,
  onAdd,
}: {
  signal: SignalRow;
  asOf: string;
  onAdd: (anchor: HTMLElement) => void;
}) {
  const meta = SIGNAL_META[signal.type];
  const strength = STRENGTH_META[signal.strength];
  const Icon = meta.icon;
  const StrengthIcon = strength.icon;
  const inSequence = signal.status === "in_sequence";

  return (
    <li className="hover:bg-muted/60 grid grid-cols-[32px_1fr_auto] items-start gap-3 px-4 py-3 transition-colors">
      <Tooltip>
        <TooltipTrigger asChild>
          <span className={cn("mt-0.5 flex size-8 items-center justify-center rounded-lg", meta.tile)}>
            <Icon className="size-4" />
          </span>
        </TooltipTrigger>
        <TooltipContent side="right">{meta.label}</TooltipContent>
      </Tooltip>

      <div className="min-w-0">
        <div className="flex min-w-0 items-center gap-1.5">
          <span className="truncate text-sm font-semibold">{signal.account.name}</span>
          <span className="text-subtle-foreground hidden truncate text-xs sm:inline">{signal.account.domain}</span>
          <Badge variant={strength.variant} className="ml-0.5">
            <StrengthIcon />
            {strength.label}
          </Badge>
        </div>
        <p className="mt-0.5 line-clamp-2 text-[13px] leading-snug">{signal.description}</p>
        <p className="text-muted-foreground mt-1 truncate text-xs">
          {signal.contact.name} · {signal.contact.title}
          <span className="text-subtle-foreground">
            {" "}
            · {signal.account.industry} · {formatNumber(signal.account.employees)} ppl · {signal.account.region}
          </span>
        </p>
      </div>

      <div className="flex flex-col items-end gap-1.5">
        <span className="text-subtle-foreground tabular text-[11px] whitespace-nowrap">
          {timeAgo(signal.detectedAt, asOf)}
        </span>
        {inSequence ? (
          <Badge variant="info" className="h-7 px-2">
            <Check />
            In sequence
          </Badge>
        ) : (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant={signal.qualified ? "default" : "outline"}
                size="xs"
                onClick={(event) => onAdd(event.currentTarget)}
              >
                <Plus />
                Add to sequence
              </Button>
            </TooltipTrigger>
            <TooltipContent side="left">
              Enroll {signal.contact.name} in “{signal.campaign.name}”
              {signal.qualified ? "" : " (signal not qualified)"}
            </TooltipContent>
          </Tooltip>
        )}
      </div>
    </li>
  );
}

export function SignalsCard({
  snapshot,
  onAddToSequence,
  className,
}: {
  snapshot: Snapshot;
  onAddToSequence: (contactId: string, campaignId: string, anchor: HTMLElement | null) => void;
  className?: string;
}) {
  const [view, setView] = useState<View>("all");
  const waiting = snapshot.signals.filter((s) => s.status === "not_contacted" && s.qualified);
  const shown = view === "action" ? waiting : snapshot.signals;

  return (
    <Card className={cn("gap-0 pb-0", className)}>
      <CardHeader className="border-b">
        <CardTitle>Buying signals</CardTitle>
        <CardDescription>
          {formatNumber(snapshot.signals.length)} detected · {formatNumber(waiting.length)} qualified and not contacted
        </CardDescription>
        <CardAction>
          <Tabs value={view} onValueChange={(value) => setView(value as View)}>
            <TabsList>
              <TabsTrigger value="all">All</TabsTrigger>
              <TabsTrigger value="action">
                Needs action
                <span className="bg-foreground/10 tabular rounded px-1 text-[10px]">{waiting.length}</span>
              </TabsTrigger>
            </TabsList>
          </Tabs>
        </CardAction>
      </CardHeader>
      <ScrollArea className="h-[440px]">
        {shown.length === 0 ? (
          <p className="text-muted-foreground px-4 py-16 text-center text-sm">
            {view === "action" ? "Every qualified signal is already in a sequence." : "No signals in this period."}
          </p>
        ) : (
          <ul className="divide-y">
            {shown.map((signal) => (
              <SignalItem
                key={signal.id}
                signal={signal}
                asOf={snapshot.asOf}
                onAdd={(anchor) => onAddToSequence(signal.contact.id, signal.campaign.id, anchor)}
              />
            ))}
          </ul>
        )}
      </ScrollArea>
    </Card>
  );
}
