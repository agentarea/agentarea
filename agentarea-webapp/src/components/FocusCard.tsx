import type { ReactNode } from "react";
import Image from "next/image";
import EntityMark from "@/components/EntityMark";
import {
  StatusIndicator,
  type StatusKind,
} from "@/components/ui/status-indicator";
import type { EntityIdentity } from "@/lib/entity-identity";

/**
 * The one card a page opened from a chat link shows (connect): the
 * AgentArea mark, then the page's header, body and footer. Phone-first: it
 * fills the screen there and becomes a card from `sm` up.
 */
export function FocusCard({ children }: { children: ReactNode }) {
  return (
    <section className="flex flex-1 flex-col gap-6 bg-card px-5 py-8 text-card-foreground sm:flex-none sm:rounded-xl sm:border sm:border-border sm:p-8 sm:shadow-sm">
      <Image
        src="/logo.svg"
        alt="AgentArea"
        width={120}
        height={32}
        priority
        className="mx-auto h-6 w-auto dark:invert"
      />
      {children}
    </section>
  );
}

/** What the link is about: the entity's mark, the question, the workspace. */
export function FocusHeader({
  identity,
  title,
  subtitle,
}: {
  identity: EntityIdentity;
  title: string;
  subtitle: string;
}) {
  return (
    <header className="flex flex-col items-center gap-3 text-center">
      <EntityMark identity={identity} className="h-12 w-12 rounded-lg" />
      <div className="space-y-1">
        <h1 className="text-balance">{title}</h1>
        <p className="text-xs text-muted-foreground">{subtitle}</p>
      </div>
    </header>
  );
}

/** Where the page's one action stands, with what to do next under it. */
export function FocusStep({
  kind,
  title,
  detail,
  children,
}: {
  kind: StatusKind;
  title: string;
  detail: string;
  children?: ReactNode;
}) {
  return (
    <div className="space-y-4">
      <div className="flex items-start gap-3">
        <StatusIndicator
          kind={kind}
          className="mt-0.5 shrink-0"
          iconClassName="h-5 w-5"
          aria-label={title}
        />
        <div className="min-w-0 space-y-1">
          <p className="text-sm font-medium">{title}</p>
          <p className="break-words text-xs text-muted-foreground">{detail}</p>
        </div>
      </div>
      {children && <div className="flex flex-col gap-2">{children}</div>}
    </div>
  );
}
