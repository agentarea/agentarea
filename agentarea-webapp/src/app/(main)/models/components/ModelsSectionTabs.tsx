import { Brain, Store } from "lucide-react";
import { ActiveLink } from "@/components/ui/active-link";

const TAB =
  "rounded-md border-b-0 px-2.5 py-1.5 font-medium hover:bg-background/70 aria-[current=page]:bg-background aria-[current=page]:shadow-sm";

/**
 * Connected models and the catalog of providers you could still add are two
 * pages, not one list with a footnote under it — the catalog is long enough
 * that it drowned the handful of providers actually in use.
 */
export default function ModelsSectionTabs({
  availableCount,
}: {
  availableCount?: number;
}) {
  return (
    <nav
      aria-label="Model sections"
      className="inline-flex items-center gap-0.5 rounded-lg bg-muted/60 p-1"
    >
      <ActiveLink href="/models" className={TAB}>
        <Brain className="h-4 w-4" />
        Connected
      </ActiveLink>
      <ActiveLink href="/models/specs" className={TAB}>
        <Store className="h-4 w-4" />
        Available
        {availableCount != null && availableCount > 0 && (
          <span className="ml-1 tabular-nums text-muted-foreground">
            {availableCount}
          </span>
        )}
      </ActiveLink>
    </nav>
  );
}
