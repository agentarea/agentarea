import type { ReactNode } from "react";
import { HeroDescription } from "./HeroDescription";

/**
 * The band at the top of a detail page's overview: the entity's mark, its name
 * with an optional status, a one-line description and a dot-separated meta row
 * of `HeroMeta` items. Shared by the agent, trigger and project overviews.
 */
export function OverviewHero({
  mark,
  title,
  status,
  description,
  showMoreLabel,
  showLessLabel,
  meta,
}: {
  /** 34px identity tile; it brings its own `mt-0.5` to sit on the title line. */
  mark: ReactNode;
  title: ReactNode;
  status?: ReactNode;
  description?: string | null;
  showMoreLabel: string;
  showLessLabel: string;
  meta?: ReactNode;
}) {
  return (
    <header className="relative overflow-hidden border-b border-border bg-gradient-to-b from-muted/30 to-background md:shrink-0">
      <span
        aria-hidden
        className="bg-hatch-soft pointer-events-none absolute inset-y-0 right-0 w-[300px] opacity-[0.35] [-webkit-mask-image:linear-gradient(90deg,transparent,#000_88%)] [mask-image:linear-gradient(90deg,transparent,#000_88%)]"
      />
      <div className="relative w-full px-4 pb-[14px] pt-[13px]">
        <div className="flex items-start gap-3">
          {mark}

          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2.5">
              <h2 className="m-0 text-[18px] font-semibold tracking-[-0.022em]">
                {title}
              </h2>
              {status}
            </div>

            {description && (
              <HeroDescription
                text={description}
                showMoreLabel={showMoreLabel}
                showLessLabel={showLessLabel}
              />
            )}

            {meta && (
              <div className="mt-1.5 flex flex-wrap items-center gap-y-1.5 text-[12px] text-muted-foreground">
                {meta}
              </div>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}
