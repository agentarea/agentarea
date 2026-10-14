import type { ComponentProps, ReactNode } from "react";
import { cn } from "../lib/utils";
import { AddButton, GroupLabel } from "./board";

/** The bordered frame a list, table or set of rows sits in. */
export function ListFrame({ className, ...props }: ComponentProps<"div">) {
  return <div className={cn("bg-card overflow-hidden rounded-lg border", className)} {...props} />;
}

/** One group of a list, under a tinted header: glyph, name, count, and an optional "new" button. */
export function ListGroup({
  title,
  glyph,
  count,
  meta,
  addLabel,
  onAdd,
  children,
}: {
  title: string;
  glyph?: ReactNode;
  count: number;
  meta?: ReactNode;
  addLabel?: string;
  onAdd?: () => void;
  children: ReactNode;
}) {
  return (
    <section aria-label={title}>
      <header className="bg-muted/70 flex h-8 min-w-0 items-center gap-2 border-b px-3">
        <GroupLabel glyph={glyph} title={title} count={count} meta={meta} />
        {onAdd && <AddButton label={addLabel ?? `New in ${title}`} onClick={onAdd} />}
      </header>
      {children}
    </section>
  );
}

/** A 36px row that opens something. */
export function ListRow({
  onOpen,
  saving = false,
  className,
  children,
}: {
  onOpen: () => void;
  saving?: boolean;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      role="button"
      tabIndex={0}
      data-saving={saving}
      onClick={onOpen}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onOpen();
        }
      }}
      className={cn(
        "hover:bg-muted/60 focus-visible:bg-muted/60 flex h-9 cursor-pointer items-center gap-2.5 border-b px-3 text-[13px] outline-none data-[saving=true]:opacity-60",
        className,
      )}
    >
      {children}
    </div>
  );
}

/** A failed action, as a line under its row. */
export function ListRowNote({ children }: { children: ReactNode }) {
  if (!children) return null;
  return (
    <p role="alert" className="text-danger border-b px-3 py-1.5 text-[11px]">
      {children}
    </p>
  );
}

/** Nothing to show, as a dashed placeholder. */
export function ListEmpty({ children }: { children: ReactNode }) {
  return (
    <p className="text-muted-foreground rounded-lg border border-dashed px-3 py-10 text-center text-sm">{children}</p>
  );
}

/** A compact list of links inside a frame: sub-issues, accounts, invoices. */
export function LinkList({ className, children }: { className?: string; children: ReactNode }) {
  return <ul className={cn("bg-card overflow-hidden rounded-lg border", className)}>{children}</ul>;
}

export function LinkRow({
  onClick,
  className,
  children,
}: {
  onClick: () => void;
  className?: string;
  children: ReactNode;
}) {
  return (
    <li className="border-b last:border-b-0">
      <button
        type="button"
        onClick={onClick}
        className={cn(
          "hover:bg-muted/60 focus-visible:bg-muted/60 flex h-9 w-full cursor-pointer items-center gap-2.5 px-3 text-left text-[13px] outline-none",
          className,
        )}
      >
        {children}
      </button>
    </li>
  );
}
