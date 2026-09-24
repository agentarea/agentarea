import { FUNNEL_STAGES, type FunnelStage } from "@shared/outreach";
import type { PersonRow, Snapshot } from "@shared/schema";
import { ChevronDown, Filter, IdCard, X } from "lucide-react";
import { useState } from "react";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { initials, timeAgo, timeUntil } from "@/lib/format";
import { SIGNAL_META, STATUS_META } from "@/lib/meta";
import { cn } from "@/lib/utils";
import { ReplyClassBadge } from "./reply-class-badge";

type View = "contacted" | "replied" | "silent";
const PAGE = 12;

const STAGE_LABELS: Record<FunnelStage, string> = {
  signals: "Signals",
  qualified: "Qualified",
  contacted: "Contacted",
  opened: "Opened",
  replied: "Replied",
  positive: "Positive",
  meeting: "Meeting",
};

const replied = (p: PersonRow) => p.replyClass !== null && p.replyClass !== "out_of_office";

function StepDots({ person }: { person: PersonRow }) {
  return (
    <div className="flex items-center gap-2">
      <div className="flex gap-1">
        {Array.from({ length: person.totalSteps }, (_, i) => (
          <span
            key={i}
            className={cn(
              "h-1.5 w-3.5 rounded-full",
              i < person.step ? "bg-foreground/70" : i === person.step && person.status === "scheduled" ? "bg-info/60" : "bg-border",
            )}
          />
        ))}
      </div>
      <span className="text-muted-foreground tabular text-xs">
        {person.step}/{person.totalSteps}
      </span>
    </div>
  );
}

export function PeopleTable({
  snapshot,
  stage,
  onClearStage,
  onOpenLead,
}: {
  snapshot: Snapshot;
  stage: FunnelStage | null;
  onClearStage: () => void;
  onOpenLead: (contactId: string) => void;
}) {
  const [view, setView] = useState<View>("contacted");
  const [expanded, setExpanded] = useState(false);

  const reachedStage = (p: PersonRow) =>
    stage === null || FUNNEL_STAGES.indexOf(p.stage) >= FUNNEL_STAGES.indexOf(stage);
  const scoped = snapshot.people.filter(reachedStage);
  const byView: Record<View, PersonRow[]> = {
    contacted: scoped,
    replied: scoped.filter(replied),
    silent: scoped.filter((p) => p.step > 0 && !replied(p)),
  };
  const rows = byView[view];
  const visible = expanded ? rows : rows.slice(0, PAGE);

  return (
    <Card className="gap-0 pb-0">
      <CardHeader className="border-b">
        <CardTitle className="flex items-center gap-2">
          People
          {stage && (
            <Badge variant="info" className="gap-1 pr-1">
              <Filter />
              Reached “{STAGE_LABELS[stage]}”
              <button
                type="button"
                onClick={onClearStage}
                className="hover:bg-info/15 ml-0.5 cursor-pointer rounded-sm p-px"
                aria-label="Clear stage filter"
              >
                <X className="size-3" />
              </button>
            </Badge>
          )}
        </CardTitle>
        <CardDescription>Everyone enrolled from a signal detected in this period · click a row for the lead card</CardDescription>
        <CardAction>
          <Tabs
            value={view}
            onValueChange={(value) => {
              setView(value as View);
              setExpanded(false);
            }}
          >
            <TabsList>
              {(
                [
                  ["contacted", "Contacted"],
                  ["replied", "Replied"],
                  ["silent", "No reply"],
                ] as const
              ).map(([key, label]) => (
                <TabsTrigger key={key} value={key}>
                  {label}
                  <span className="bg-foreground/10 tabular rounded px-1 text-[10px]">{byView[key].length}</span>
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
        </CardAction>
      </CardHeader>

      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className="pl-4">Person</TableHead>
            <TableHead>Company</TableHead>
            <TableHead>Signal</TableHead>
            <TableHead>Sequence</TableHead>
            <TableHead>Last touch</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="w-10 pr-4">
              <span className="sr-only">Open lead card</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {visible.length === 0 ? (
            <TableRow className="hover:bg-transparent">
              <TableCell colSpan={7} className="text-muted-foreground py-12 text-center text-sm">
                Nobody here for this period and filter.
              </TableCell>
            </TableRow>
          ) : (
            visible.map((person) => {
              const signal = person.signal ? SIGNAL_META[person.signal.type] : null;
              const SignalIcon = signal?.icon;
              const status = STATUS_META[person.status];
              return (
                <TableRow
                  key={person.contactId}
                  className="group cursor-pointer"
                  onClick={() => onOpenLead(person.contactId)}
                >
                  <TableCell className="pl-4">
                    <div className="flex items-center gap-2.5">
                      <Avatar className="size-7">
                        <AvatarFallback className="bg-secondary text-[10px] font-semibold">
                          {initials(person.name)}
                        </AvatarFallback>
                      </Avatar>
                      <div className="min-w-0">
                        <div className="truncate font-medium">{person.name}</div>
                        <div className="text-muted-foreground max-w-[200px] truncate text-xs">{person.title}</div>
                      </div>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="font-medium">{person.company}</div>
                    <div className="text-subtle-foreground text-xs">{person.domain}</div>
                  </TableCell>
                  <TableCell className="max-w-[320px]">
                    {person.signal && signal && SignalIcon ? (
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <div className="flex min-w-0 items-center gap-2">
                            <span
                              className={cn("flex size-6 shrink-0 items-center justify-center rounded-md", signal.tile)}
                            >
                              <SignalIcon className="size-3.5" />
                            </span>
                            <span className="truncate text-xs">{person.signal.description}</span>
                          </div>
                        </TooltipTrigger>
                        <TooltipContent>
                          {signal.label} · detected {timeAgo(person.signal.detectedAt, snapshot.asOf)}
                        </TooltipContent>
                      </Tooltip>
                    ) : (
                      <span className="text-subtle-foreground text-xs">—</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <StepDots person={person} />
                    <div className="text-subtle-foreground mt-1 max-w-[180px] truncate text-[11px]">
                      {person.campaign.name}
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="tabular text-xs">
                      {person.lastTouchAt ? timeAgo(person.lastTouchAt, snapshot.asOf) : "—"}
                    </div>
                    {person.nextTouchAt && (
                      <div className="text-subtle-foreground tabular mt-0.5 text-[11px]">
                        next {timeUntil(person.nextTouchAt, snapshot.asOf)}
                      </div>
                    )}
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-1.5">
                      {person.replyClass && person.status !== "meeting" && person.status !== "unsubscribed" ? (
                        <ReplyClassBadge classification={person.replyClass} />
                      ) : (
                        <Badge variant={status.variant}>{status.label}</Badge>
                      )}
                    </div>
                  </TableCell>
                  <TableCell className="pr-4">
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button
                          variant="ghost"
                          size="xs"
                          aria-label={`Open ${person.name}'s lead card`}
                          className="text-subtle-foreground group-hover:text-foreground group-hover:bg-accent"
                          onClick={(event) => {
                            event.stopPropagation();
                            onOpenLead(person.contactId);
                          }}
                        >
                          <IdCard />
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent side="left">Open lead card</TooltipContent>
                    </Tooltip>
                  </TableCell>
                </TableRow>
              );
            })
          )}
        </TableBody>
      </Table>

      {rows.length > PAGE && (
        <div className="border-t p-1.5">
          <Button
            variant="ghost"
            size="sm"
            className="text-muted-foreground w-full"
            onClick={() => setExpanded((value) => !value)}
          >
            <ChevronDown className={cn("transition-transform", expanded && "rotate-180")} />
            {expanded ? "Show fewer" : `Show all ${rows.length}`}
          </Button>
        </div>
      )}
    </Card>
  );
}
