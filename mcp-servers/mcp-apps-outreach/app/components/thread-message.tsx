import type { ThreadMessage as Message } from "@shared/schema";
import { Eye, MousePointerClick } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

/** One email in a thread timeline; put inside an <ol> that draws the rail. */
export function ThreadMessage({ message, accent }: { message: Message; accent: string }) {
  const inbound = message.direction === "inbound";
  return (
    <li className="relative pl-6">
      <span
        className={cn(
          "ring-background absolute top-1.5 left-0 size-2.5 rounded-full ring-4",
          inbound ? "" : "bg-border",
        )}
        style={inbound ? { background: accent } : undefined}
      />
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
        <span className="font-medium">{message.from}</span>
        {message.step !== null && <Badge variant="secondary">Step {message.step}</Badge>}
        <span className="text-subtle-foreground tabular">{formatDateTime(message.at)}</span>
      </div>
      <div
        className={cn(
          "mt-2 rounded-lg border p-3",
          inbound ? "bg-card shadow-xs" : "bg-muted/60 border-transparent",
        )}
        style={inbound ? { borderColor: `color-mix(in oklab, ${accent} 45%, var(--border))` } : undefined}
      >
        <p className="text-xs font-semibold">{message.subject}</p>
        <p className="text-foreground/90 mt-1.5 text-[13px] leading-relaxed whitespace-pre-line">{message.body}</p>
      </div>
      {!inbound && (message.openedAt || message.clickedAt) && (
        <div className="text-subtle-foreground mt-1.5 flex gap-3 text-[11px]">
          {message.openedAt && (
            <span className="flex items-center gap-1">
              <Eye className="size-3" /> Opened {formatDateTime(message.openedAt)}
            </span>
          )}
          {message.clickedAt && (
            <span className="flex items-center gap-1">
              <MousePointerClick className="size-3" /> Clicked
            </span>
          )}
        </div>
      )}
    </li>
  );
}
