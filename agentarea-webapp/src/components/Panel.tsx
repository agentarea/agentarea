import type { ReactNode } from "react";

/** A static titled panel on a page: the surface of Design.md "Surfaces" (b), not a clickable card. */
export default function Panel({
  title,
  count,
  children,
}: {
  title: string;
  count?: number;
  children: ReactNode;
}) {
  return (
    <section className="mb-4 rounded-md border border-zinc-200 bg-white card-shadow dark:border-zinc-700 dark:bg-zinc-800">
      <header className="flex items-center justify-between border-b border-zinc-200 px-4 py-3 dark:border-zinc-700">
        <h2 className="text-base font-semibold">{title}</h2>
        {count !== undefined && (
          <span className="note tabular-nums">{count}</span>
        )}
      </header>
      {children}
    </section>
  );
}
