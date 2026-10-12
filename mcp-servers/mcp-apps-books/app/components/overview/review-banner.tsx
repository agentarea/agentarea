import { Callout, InlineStatus, toStatus, type Status } from "@kit/components/notes";
import { Button } from "@kit/ui/button";
import type { Overview } from "@shared/schema";
import { ArrowRight, Inbox } from "lucide-react";
import { useState } from "react";
import { dayMonth } from "@/lib/format";

export function ReviewBanner({ overview, onReview }: { overview: Overview; onReview: () => Promise<string | null> }) {
  const [status, setStatus] = useState<Status>(null);
  const { count, oldest } = overview.uncategorized;
  if (count === 0) return null;
  return (
    <Callout
      tone="warning"
      icon={<Inbox />}
      action={
        <>
          <InlineStatus status={status} />
          <Button
            size="xs"
            variant="outline"
            className="text-foreground"
            onClick={async () => setStatus(await toStatus(onReview()))}
          >
            Review
            <ArrowRight />
          </Button>
        </>
      }
    >
      {count} uncategorized transactions
      <span className="font-normal opacity-80">
        {" "}
        · oldest from {oldest ? dayMonth(oldest, overview.today) : "—"}; they count in the P&L as Uncategorized until
        sorted
      </span>
    </Callout>
  );
}
