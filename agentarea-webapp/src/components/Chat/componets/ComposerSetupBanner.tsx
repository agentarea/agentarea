import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { StartAgentButton } from "@/components/ui/start-agent-button";
import { cn } from "@/lib/utils";

interface ComposerSetupBannerProps {
  step: number;
  totalSteps: number;
  title: string;
  description: string;
  actionLabel: string;
  href: string;
  className?: string;
}

/**
 * The one thing standing between the user and a working composer, docked on
 * top of it. Placed directly above a composer: the bottom edge slides under the
 * composer's top border, so the two read as one piece rather than as a notice
 * floating somewhere on the page.
 */
export function ComposerSetupBanner({
  step,
  totalSteps,
  title,
  description,
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
      {/* Always one row. A phone has no room for the description or a
          labelled button, so it gets the title and an arrow instead. */}
      <div className="relative flex items-center gap-3 px-3 py-2.5">
        <Badge className="shrink-0 tabular-nums">
          {step}/{totalSteps}
        </Badge>
        <p className="min-w-0 flex-1 text-[13px] leading-5 text-muted-foreground">
          <span className="font-medium text-foreground">{title}</span>
          <span className="hidden sm:inline"> {description}</span>
        </p>
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
