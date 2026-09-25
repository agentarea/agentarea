import type { ReplyClass } from "@shared/outreach";
import { Badge } from "@/components/ui/badge";
import { REPLY_META } from "@/lib/meta";
import { cn } from "@/lib/utils";

export function ReplyClassBadge({ classification, className }: { classification: ReplyClass; className?: string }) {
  const meta = REPLY_META[classification];
  return (
    <Badge
      variant="outline"
      className={cn("gap-1.5 border-transparent", className)}
      style={{
        color: meta.color,
        background: `color-mix(in oklab, ${meta.color} 13%, transparent)`,
      }}
    >
      <span className="size-1.5 rounded-full" style={{ background: meta.color }} />
      {meta.label}
    </Badge>
  );
}
