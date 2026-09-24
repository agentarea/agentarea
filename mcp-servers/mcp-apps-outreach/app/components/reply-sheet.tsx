import type { ReplyRow } from "@shared/schema";
import { CalendarCheck, Check, IdCard, Lightbulb } from "lucide-react";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { formatCurrency, formatDateTime, initials, timeAgo } from "@/lib/format";
import { REPLY_META, SIGNAL_META, STRENGTH_META } from "@/lib/meta";
import { cn } from "@/lib/utils";
import { ReplyClassBadge } from "./reply-class-badge";
import { ThreadMessage } from "./thread-message";

export type SheetAnchor = { top: number; height: number };

export function ReplySheet({
  reply,
  asOf,
  anchor,
  onOpenChange,
  onMarkHandled,
  onOpenLead,
}: {
  reply: ReplyRow | null;
  asOf: string;
  anchor: SheetAnchor;
  onOpenChange: (open: boolean) => void;
  onMarkHandled: (replyId: string, anchor: HTMLElement | null) => void;
  onOpenLead: (contactId: string) => void;
}) {
  const accent = reply ? REPLY_META[reply.classification].color : "var(--border)";
  const signal = reply?.signal;
  const signalMeta = signal ? SIGNAL_META[signal.type] : null;
  const SignalIcon = signalMeta?.icon;

  return (
    <Sheet open={reply !== null} onOpenChange={onOpenChange}>
      <SheetContent
        className="right-2 gap-0 rounded-xl border sm:max-w-[560px]"
        style={{ top: anchor.top, height: anchor.height, bottom: "auto" }}
      >
        {reply && (
          <>
            <SheetHeader className="border-b pr-10">
              <div className="flex items-center gap-3">
                <Avatar className="size-10">
                  <AvatarFallback className="bg-secondary text-xs font-semibold">
                    {initials(reply.contact.name)}
                  </AvatarFallback>
                </Avatar>
                <div className="min-w-0">
                  <SheetTitle className="truncate">{reply.contact.name}</SheetTitle>
                  <SheetDescription className="truncate text-xs">
                    {reply.contact.title} · {reply.account.name} · {reply.contact.email}
                  </SheetDescription>
                </div>
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                <ReplyClassBadge classification={reply.classification} />
                <Badge variant="outline">{reply.campaign.name}</Badge>
                {reply.meeting && (
                  <Badge variant="success">
                    <CalendarCheck />
                    {formatDateTime(reply.meeting.scheduledFor)} · {formatCurrency(reply.meeting.pipelineValue)}
                  </Badge>
                )}
                <span className="text-subtle-foreground ml-auto text-[11px]">
                  replied {timeAgo(reply.receivedAt, asOf)}
                </span>
              </div>
            </SheetHeader>

            <ScrollArea className="min-h-0 flex-1">
              <div className="flex flex-col gap-5 p-4">
                {signal && signalMeta && SignalIcon && (
                  <section>
                    <h3 className="text-subtle-foreground mb-2 text-[10px] font-semibold tracking-wider uppercase">
                      Triggered by
                    </h3>
                    <div className="flex items-start gap-3 rounded-lg border p-3">
                      <span className={cn("flex size-8 shrink-0 items-center justify-center rounded-lg", signalMeta.tile)}>
                        <SignalIcon className="size-4" />
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium">{signal.description}</p>
                        <p className="text-muted-foreground mt-0.5 text-xs">
                          {signalMeta.label} · {STRENGTH_META[signal.strength].label} · detected{" "}
                          {timeAgo(signal.detectedAt, asOf)}
                        </p>
                      </div>
                    </div>
                  </section>
                )}

                <section>
                  <h3 className="text-subtle-foreground mb-3 text-[10px] font-semibold tracking-wider uppercase">
                    Thread · {reply.thread.length} messages
                  </h3>
                  <ol className="before:bg-border relative flex flex-col gap-5 before:absolute before:top-2 before:bottom-2 before:left-[4.5px] before:w-px">
                    {reply.thread.map((message, index) => (
                      <ThreadMessage key={index} message={message} accent={accent} />
                    ))}
                  </ol>
                </section>
              </div>
            </ScrollArea>

            <SheetFooter className="gap-3 border-t">
              <div className="bg-info-surface flex gap-2.5 rounded-lg p-3">
                <Lightbulb className="text-info mt-0.5 size-4 shrink-0" />
                <div>
                  <p className="text-info text-[10px] font-semibold tracking-wider uppercase">Suggested next step</p>
                  <p className="mt-0.5 text-[13px] leading-snug">{reply.suggestedNextStep}</p>
                </div>
              </div>
              <div className="flex justify-end gap-2">
                <Button variant="ghost" size="sm" className="mr-auto" onClick={() => onOpenLead(reply.contact.id)}>
                  <IdCard />
                  Open lead card
                </Button>
                <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
                  Close
                </Button>
                <Button
                  size="sm"
                  disabled={reply.handled}
                  onClick={(event) => onMarkHandled(reply.id, event.currentTarget)}
                >
                  <Check />
                  {reply.handled ? "Handled" : "Mark handled"}
                </Button>
              </div>
            </SheetFooter>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
