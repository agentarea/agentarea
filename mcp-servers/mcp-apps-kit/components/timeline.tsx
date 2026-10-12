import type { ReactNode } from "react";
import { useState } from "react";
import { SendHorizontal } from "lucide-react";
import { Button } from "../ui/button";
import { Textarea } from "../ui/textarea";
import { FieldNote } from "./notes";
import { AgentTag, PersonAvatar, type Person } from "./person-avatar";

/** Emphasis inside a timeline sentence: names, values, statuses. */
export const Strong = ({ children }: { children: ReactNode }) => (
  <span className="text-foreground font-medium">{children}</span>
);

/** A relative time with the exact one on hover. */
export function When({ at, label, title }: { at: string; label: string; title?: string }) {
  return (
    <time dateTime={at} title={title} className="text-subtle-foreground shrink-0 text-[11px]">
      {label}
    </time>
  );
}

export function Timeline({ children }: { children: ReactNode }) {
  return <ol className="flex flex-col gap-3">{children}</ol>;
}

/** One line of history: "Priya moved it from Todo to Done", the actor's avatar, the time. */
export function TimelineEvent({
  actor,
  icon,
  when,
  children,
}: {
  actor?: Person | null;
  icon?: ReactNode;
  when?: ReactNode;
  children: ReactNode;
}) {
  return (
    <li className="text-muted-foreground flex items-start gap-2 px-1 text-xs leading-5">
      {icon ?? <PersonAvatar person={actor ?? null} className="mt-0.5 size-4" />}
      <div className="min-w-0 flex-1">{children}</div>
      {when}
    </li>
  );
}

/** A comment or note: a bordered card with its author on top. */
export function TimelineCard({
  author,
  title,
  when,
  aside,
  children,
}: {
  author?: Person | null;
  title?: ReactNode;
  when?: ReactNode;
  aside?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <li className="bg-card rounded-lg border px-3 py-2.5">
      <div className="mb-1.5 flex items-center gap-2 text-xs last:mb-0">
        {aside}
        {author !== undefined && <PersonAvatar person={author} />}
        <span className="min-w-0 truncate font-medium">{title ?? author?.name}</span>
        {author?.kind === "agent" && <AgentTag />}
        {when && <span className="ml-auto shrink-0">{when}</span>}
      </div>
      {children}
    </li>
  );
}

/** A textarea that submits with the button or Cmd/Ctrl+Enter, with its status under it. */
export function Composer({
  placeholder,
  label,
  submitLabel,
  busyLabel = "Posting…",
  busy,
  note,
  onSubmit,
}: {
  placeholder: string;
  label: string;
  submitLabel: string;
  busyLabel?: string;
  busy?: boolean;
  note?: string | null;
  onSubmit: (body: string) => Promise<boolean>;
}) {
  const [body, setBody] = useState("");
  const submit = async () => {
    if (!body.trim() || busy) return;
    if (await onSubmit(body.trim())) setBody("");
  };
  return (
    <form
      className="flex flex-col gap-1.5"
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <Textarea
        value={body}
        onChange={(event) => setBody(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
            event.preventDefault();
            void submit();
          }
        }}
        placeholder={placeholder}
        aria-label={label}
        aria-invalid={note ? true : undefined}
        disabled={busy}
      />
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 pt-1">
          <FieldNote busy={busy} note={note ?? undefined} label={busyLabel} />
        </div>
        <Button type="submit" size="xs" disabled={!body.trim() || busy}>
          <SendHorizontal />
          {submitLabel}
        </Button>
      </div>
    </form>
  );
}
