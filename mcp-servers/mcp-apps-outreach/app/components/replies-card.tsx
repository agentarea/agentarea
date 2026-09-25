import type { Snapshot } from "@shared/schema";
import { IdCard } from "lucide-react";
import { useState } from "react";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { initials, timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";
import { ReplyClassBadge } from "./reply-class-badge";
import { ReplySheet, type SheetAnchor } from "./reply-sheet";

type View = "open" | "all";

export function RepliesCard({
  snapshot,
  onMarkHandled,
  onOpenLead,
  className,
}: {
  snapshot: Snapshot;
  onMarkHandled: (replyId: string, anchor: HTMLElement | null) => void;
  onOpenLead: (contactId: string) => void;
  className?: string;
}) {
  const [view, setView] = useState<View>("open");
  const [openId, setOpenId] = useState<string | null>(null);
  const [anchor, setAnchor] = useState<SheetAnchor>({ top: 8, height: 640 });
  const open = snapshot.replies.filter((r) => !r.handled);
  const shown = view === "open" ? open : snapshot.replies;
  const selected = snapshot.replies.find((r) => r.id === openId) ?? null;

  const openThread = (id: string, row: HTMLElement) => {
    // Keep the panel next to the row: the frame may be far taller than the screen.
    const viewport = window.innerHeight;
    const height = Math.min(760, viewport - 16);
    const top = Math.min(Math.max(row.getBoundingClientRect().top - 96, 8), Math.max(viewport - height - 8, 8));
    setAnchor({ top, height });
    setOpenId(id);
  };

  return (
    <Card className={cn("gap-0 pb-0", className)}>
      <CardHeader className="border-b">
        <CardTitle className="flex items-center gap-2">
          Replies
          {open.length > 0 && (
            <span className="bg-danger-surface text-danger tabular rounded-full px-1.5 text-[11px] leading-5 font-semibold">
              {open.length}
            </span>
          )}
        </CardTitle>
        <CardDescription>Click a reply to read the thread</CardDescription>
        <CardAction>
          <Tabs value={view} onValueChange={(value) => setView(value as View)}>
            <TabsList>
              <TabsTrigger value="open">To handle</TabsTrigger>
              <TabsTrigger value="all">All</TabsTrigger>
            </TabsList>
          </Tabs>
        </CardAction>
      </CardHeader>
      <ScrollArea className="h-[440px]">
        {shown.length === 0 ? (
          <p className="text-muted-foreground px-4 py-16 text-center text-sm">
            {view === "open" ? "Inbox zero — every reply is handled." : "No replies in this period."}
          </p>
        ) : (
          <ul className="divide-y">
            {shown.map((reply) => (
              <li key={reply.id} className="group relative">
                <button
                  type="button"
                  onClick={(event) => openThread(reply.id, event.currentTarget)}
                  className="hover:bg-muted/60 focus-visible:bg-muted/60 grid w-full cursor-pointer grid-cols-[32px_1fr] gap-3 px-4 py-3 text-left transition-colors outline-none"
                >
                  <span className="relative">
                    <Avatar className="size-8">
                      <AvatarFallback className="bg-secondary text-[11px] font-semibold">
                        {initials(reply.contact.name)}
                      </AvatarFallback>
                    </Avatar>
                    {!reply.handled && (
                      <span
                        className="bg-info ring-card absolute -top-0.5 -right-0.5 size-2.5 rounded-full ring-2"
                        aria-label="Needs handling"
                      />
                    )}
                  </span>
                  <span className="min-w-0">
                    <span className="flex items-center gap-2">
                      <span className={cn("truncate text-sm", reply.handled ? "font-medium" : "font-semibold")}>
                        {reply.contact.name}
                      </span>
                      <span className="text-subtle-foreground tabular ml-auto shrink-0 text-[11px] transition-opacity group-focus-within:opacity-0 group-hover:opacity-0">
                        {timeAgo(reply.receivedAt, snapshot.asOf)}
                      </span>
                    </span>
                    <span className="text-muted-foreground block truncate text-xs">
                      {reply.contact.title} · {reply.account.name}
                    </span>
                    <span className="mt-1.5 flex items-start gap-2">
                      <ReplyClassBadge classification={reply.classification} className="shrink-0" />
                      <span className="text-muted-foreground line-clamp-2 text-xs leading-snug">{reply.body}</span>
                    </span>
                  </span>
                </button>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      variant="outline"
                      size="xs"
                      onClick={() => onOpenLead(reply.contact.id)}
                      className="bg-card absolute top-2 right-3 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100"
                    >
                      <IdCard />
                      Card
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent side="left">Open {reply.contact.name}'s lead card</TooltipContent>
                </Tooltip>
              </li>
            ))}
          </ul>
        )}
      </ScrollArea>
      <ReplySheet
        reply={selected}
        asOf={snapshot.asOf}
        anchor={anchor}
        onOpenChange={(isOpen) => !isOpen && setOpenId(null)}
        onMarkHandled={onMarkHandled}
        onOpenLead={onOpenLead}
      />
    </Card>
  );
}
