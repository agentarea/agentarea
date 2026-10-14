import { Loader2, Plus } from "lucide-react";
import { useState, type DragEvent, type ReactNode } from "react";
import { cn } from "../lib/utils";
import { Button } from "../ui/button";

/**
 * Drag state for a board: cards carry their id, columns accept them.
 * `column(key)` and `card(id)` return the props to spread on each.
 */
export function useBoardDrag<C extends string>(onDrop: (id: string, column: C) => void, type = "text/plain") {
  const [dragging, setDragging] = useState<string | null>(null);
  const [over, setOver] = useState<C | null>(null);
  const column = (key: C): ColumnDrop => ({
    over: over === key,
    onDragOver: (event: DragEvent) => {
      if (!dragging) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
      if (over !== key) setOver(key);
    },
    onDragLeave: (event: DragEvent) => {
      if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setOver(null);
    },
    onDrop: (event: DragEvent) => {
      event.preventDefault();
      setOver(null);
      setDragging(null);
      const id = event.dataTransfer.getData(type);
      if (id) onDrop(id, key);
    },
  });
  const card = (id: string) => ({
    dragging: dragging === id,
    onDragStart: (event: DragEvent) => {
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData(type, id);
      setDragging(id);
    },
    onDragEnd: () => {
      setDragging(null);
      setOver(null);
    },
  });
  return { dragging, over, column, card };
}

export type ColumnDrop = {
  over: boolean;
  onDragOver: (event: DragEvent) => void;
  onDragLeave: (event: DragEvent) => void;
  onDrop: (event: DragEvent) => void;
};

/** Columns scroll sideways inside the page gutter; the page itself never does. */
export function BoardScroller({ children }: { children: ReactNode }) {
  return (
    <div className="-mx-3 overflow-x-auto px-3 pb-2 sm:-mx-5 sm:px-5">
      <div className="flex w-max items-start gap-3">{children}</div>
    </div>
  );
}

/** Glyph, name and count: the head of a board column and of a list group. */
export function GroupLabel({
  glyph,
  title,
  count,
  meta,
}: {
  glyph?: ReactNode;
  title: ReactNode;
  count: number;
  meta?: ReactNode;
}) {
  return (
    <>
      {glyph}
      <h2 className="truncate text-[13px] font-medium">{title}</h2>
      <span className="text-muted-foreground tabular text-xs">{count}</span>
      {meta !== undefined && <span className="text-subtle-foreground tabular truncate text-xs">{meta}</span>}
    </>
  );
}

function AddButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <Button
      variant="ghost"
      size="icon"
      className="text-muted-foreground ml-auto size-6"
      aria-label={label}
      onClick={onClick}
    >
      <Plus className="size-3.5" />
    </Button>
  );
}

export function BoardColumn({
  title,
  glyph,
  count,
  meta,
  addLabel,
  onAdd,
  drop,
  empty,
  children,
}: {
  title: string;
  glyph?: ReactNode;
  count: number;
  meta?: ReactNode;
  addLabel?: string;
  onAdd?: () => void;
  drop?: ColumnDrop;
  /** Shown instead of cards when there are none. */
  empty?: ReactNode;
  children?: ReactNode;
}) {
  const { over = false, ...handlers } = drop ?? {};
  return (
    <section
      aria-label={title}
      data-over={over}
      {...handlers}
      className="bg-muted/70 data-[over=true]:ring-ring/40 data-[over=true]:bg-accent/70 flex w-[272px] shrink-0 flex-col gap-1.5 rounded-lg p-1.5 transition-colors data-[over=true]:ring-2"
    >
      <header className="flex h-7 min-w-0 items-center gap-2 px-1.5">
        <GroupLabel glyph={glyph} title={title} count={count} meta={meta} />
        {onAdd && <AddButton label={addLabel ?? `New in ${title}`} onClick={onAdd} />}
      </header>
      {children}
      {empty && <p className="text-subtle-foreground px-1.5 py-3 text-center text-xs">{empty}</p>}
    </section>
  );
}

/** One card on a board: opens on click or Enter, drags to another column. */
export function BoardCard({
  label,
  saving = false,
  dragging = false,
  draggable = true,
  onOpen,
  onDragStart,
  onDragEnd,
  className,
  children,
}: {
  label: string;
  saving?: boolean;
  dragging?: boolean;
  draggable?: boolean;
  onOpen: () => void;
  onDragStart?: (event: DragEvent) => void;
  onDragEnd?: () => void;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      role="button"
      tabIndex={0}
      draggable={draggable && !saving}
      aria-label={label}
      data-saving={saving}
      data-dragging={dragging}
      onClick={onOpen}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onOpen();
        }
      }}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      className={cn(
        "bg-card hover:border-input focus-visible:ring-ring/50 group cursor-pointer rounded-md border p-2.5 shadow-xs transition-[opacity,border-color] outline-none select-none focus-visible:ring-[3px] data-[dragging=true]:opacity-40 data-[saving=true]:opacity-60",
        className,
      )}
    >
      {children}
    </div>
  );
}

/** A failed action, under the card or row it belongs to. */
export function CardNote({ children }: { children: ReactNode }) {
  if (!children) return null;
  return (
    <p role="alert" className="text-danger mt-2 text-[11px] leading-snug">
      {children}
    </p>
  );
}

/** Inline "new item" at the top of a column or group: fields, then Cancel / Create. */
export function InlineForm({
  busy,
  error,
  canSubmit,
  submitLabel = "Create",
  extra,
  onSubmit,
  onClose,
  children,
}: {
  busy: boolean;
  error: string | null;
  canSubmit: boolean;
  submitLabel?: string;
  /** Controls on the left of the buttons. */
  extra?: ReactNode;
  onSubmit: () => void;
  onClose: () => void;
  children: ReactNode;
}) {
  return (
    <form
      className="bg-card flex flex-col gap-2 rounded-md border p-2 shadow-xs"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape") onClose();
      }}
    >
      {children}
      <div className="flex items-center gap-1.5">
        {extra}
        <Button type="button" variant="ghost" size="xs" className="ml-auto" onClick={onClose} disabled={busy}>
          Cancel
        </Button>
        <Button type="submit" size="xs" disabled={busy || !canSubmit}>
          {busy && <Loader2 className="animate-spin" />}
          {submitLabel}
        </Button>
      </div>
      {error && (
        <p role="alert" className="text-danger text-[11px] leading-snug">
          {error}
        </p>
      )}
    </form>
  );
}

export { AddButton };
