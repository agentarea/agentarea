import { Loader2 } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "../lib/utils";

/** The inline status line under a control: "Saving…" while in flight, the error if it failed. */
export function FieldNote({ busy, note, label = "Saving…" }: { busy?: boolean; note?: string | null; label?: string }) {
  if (busy) {
    return (
      <p className="text-muted-foreground flex items-center gap-1 text-[11px]" aria-live="polite">
        <Loader2 className="size-3 animate-spin" />
        {label}
      </p>
    );
  }
  if (!note) return null;
  return (
    <p role="alert" className="text-danger text-[11px] leading-snug">
      {note}
    </p>
  );
}

export type Status = { kind: "busy" | "ok" | "error"; text: string } | null;

/** The outcome of an action, next to the control that started it. Never a toast. */
export function InlineStatus({ status, className }: { status: Status; className?: string }) {
  if (!status) return null;
  return (
    <span
      role={status.kind === "error" ? "alert" : "status"}
      className={cn(
        "inline-flex min-w-0 items-center gap-1 text-[11px] leading-snug",
        status.kind === "error" && "text-danger",
        status.kind === "ok" && "text-success",
        status.kind === "busy" && "text-muted-foreground",
        className,
      )}
    >
      {status.kind === "busy" && <Loader2 className="size-3 shrink-0 animate-spin" />}
      {status.text}
    </span>
  );
}

/** A pending "error message or null" as a status: nothing on success. */
export async function toStatus(pending: Promise<string | null>): Promise<Status> {
  const error = await pending;
  return error ? { kind: "error", text: error } : null;
}

const CALLOUT_TONES = {
  danger: "border-danger/30 bg-danger-surface text-danger",
  warning: "border-warning/30 bg-warning-surface text-warning",
  info: "border-info/30 bg-info-surface text-info",
};

/** A tinted strip for what needs attention: a failure, something to review. */
export function Callout({
  tone,
  icon,
  action,
  children,
  className,
  role,
}: {
  tone: keyof typeof CALLOUT_TONES;
  icon?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  role?: string;
}) {
  return (
    <div
      role={role}
      className={cn(
        "rounded-lg border px-3 py-2 text-xs font-medium",
        (icon || action) && "flex flex-wrap items-center gap-x-2 gap-y-1.5 [&>svg]:size-3.5 [&>svg]:shrink-0",
        CALLOUT_TONES[tone],
        className,
      )}
    >
      {icon}
      {icon || action ? <div className="min-w-0 flex-1">{children}</div> : children}
      {action}
    </div>
  );
}

export function ErrorBanner({ message }: { message: string | null | undefined }) {
  if (!message) return null;
  return (
    <Callout tone="danger" role="alert">
      {message}
    </Callout>
  );
}
