import { ArrowRight, Check } from "lucide-react";
import Link from "@/components/WorkspaceLink";
import { Button } from "@/components/ui/button";
import { StartAgentButton } from "@/components/ui/start-agent-button";
import { cn } from "@/lib/utils";

type StepState = "done" | "current" | "upcoming";

interface ComposerSetupBannerProps {
  /** Every step, in order. */
  steps: string[];
  /** Index of the step to do now; the ones before it are done. */
  current: number;
  actionLabel: string;
  href: string;
  className?: string;
}

/**
 * What stands between the user and a working composer, docked on top of it:
 * the setup steps in a row, where you are in them, and the button for the
 * current one. Placed directly above a composer: the bottom edge slides under
 * the composer's top border, so the two read as one piece rather than as a
 * notice floating somewhere on the page.
 */
export function ComposerSetupBanner({
  steps,
  current,
  actionLabel,
  href,
  className,
}: ComposerSetupBannerProps) {
  return (
    // pb-3 is the strip the composer covers (-mb-3); the content keeps its own
    // even padding above it so it stays vertically centred in what is visible.
    <div
      className={cn(
        "-mb-3 mx-3 rounded-t-xl border border-b-0 bg-card pb-3 sm:mx-5",
        className
      )}
    >
      <div className="relative flex items-center gap-3 px-3 py-2">
        <ol className="flex min-w-0 flex-1 items-center gap-2">
          {steps.map((label, index) => {
            const state: StepState =
              index < current
                ? "done"
                : index === current
                  ? "current"
                  : "upcoming";
            return (
              <li
                key={label}
                aria-current={state === "current" ? "step" : undefined}
                className="flex min-w-0 items-center gap-2"
              >
                {index > 0 ? (
                  // Blue, like the current step's ring, once the step before
                  // it is done.
                  <span
                    aria-hidden
                    className={cn(
                      "h-px w-5 shrink-0 sm:w-10",
                      index <= current ? "bg-primary" : "bg-border"
                    )}
                  />
                ) : null}
                <StepMark state={state} number={index + 1} />
                {/* A phone keeps only the current step's name. */}
                <span
                  className={cn(
                    "truncate text-[13px] leading-5",
                    state === "current"
                      ? "font-medium text-foreground"
                      : "hidden text-muted-foreground sm:inline"
                  )}
                >
                  {label}
                </span>
              </li>
            );
          })}
        </ol>

        {/* The catalog's Connect button, without the logo; it draws its own
            arrow. */}
        <StartAgentButton
          asChild
          size="2xs"
          showLogo={false}
          className="hidden w-auto shrink-0 sm:flex"
        >
          <Link href={href}>{actionLabel}</Link>
        </StartAgentButton>
        {/* Dressed like the composer's send button below it. Too small to aim
            at with a thumb, so its hit area (after:) covers the whole row. */}
        <Button
          asChild
          size="icon"
          className="h-7 w-7 shrink-0 rounded-md bg-foreground text-background shadow-none after:absolute after:inset-0 hover:bg-foreground/85 sm:hidden"
        >
          <Link href={href} aria-label={actionLabel}>
            <ArrowRight />
          </Link>
        </Button>
      </div>
    </div>
  );
}

/** The circle for one step: a tick once done, its number otherwise. */
function StepMark({ state, number }: { state: StepState; number: number }) {
  if (state === "done") {
    // StatusIndicator's brand halo: a soft tint, not a solid fill — the same
    // blue as the current step and the line between them.
    return (
      <span className="flex size-4 shrink-0 items-center justify-center rounded-full bg-primary/15 text-primary">
        <Check className="size-2.5" strokeWidth={3} aria-hidden />
      </span>
    );
  }
  return (
    <span
      className={cn(
        "flex size-4 shrink-0 items-center justify-center rounded-full text-[10px] font-medium leading-none tabular-nums",
        state === "current"
          ? "border-[1.5px] border-primary text-primary"
          : "border border-zinc-300 text-zinc-400 dark:border-zinc-600 dark:text-zinc-500"
      )}
    >
      {number}
    </span>
  );
}
