import { cn } from "../lib/utils";

export type GlyphShape = "planned" | "open" | "done" | "canceled";

/**
 * Linear-style progress glyph: a dashed ring for planned, a ring that fills
 * with `progress` (0..1) for open, a filled check for done, a filled cross for canceled.
 */
export function StatusGlyph({
  shape,
  progress,
  color,
  className,
}: {
  shape: GlyphShape;
  progress?: number;
  color: string;
  className?: string;
}) {
  return (
    <svg viewBox="0 0 14 14" className={cn("size-3.5 shrink-0", className)} style={{ color }} aria-hidden>
      {shape === "planned" ? (
        <circle cx="7" cy="7" r="6" fill="none" stroke="currentColor" strokeWidth="1.5" strokeDasharray="2.2 1.9" />
      ) : shape === "done" || shape === "canceled" ? (
        <>
          <circle cx="7" cy="7" r="6.75" fill="currentColor" />
          {shape === "done" ? (
            <path
              d="M4.3 7.2 6.1 9 9.7 5.2"
              fill="none"
              stroke="var(--background)"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          ) : (
            <path d="M5 5l4 4M9 5 5 9" stroke="var(--background)" strokeWidth="1.5" strokeLinecap="round" />
          )}
        </>
      ) : (
        <>
          <circle cx="7" cy="7" r="6" fill="none" stroke="currentColor" strokeWidth="1.5" />
          {progress !== undefined && progress > 0 && (
            <circle
              cx="7"
              cy="7"
              r="1.75"
              fill="none"
              stroke="currentColor"
              strokeWidth="3.5"
              strokeDasharray={`${2 * Math.PI * 1.75 * Math.min(progress, 1)} ${2 * Math.PI * 1.75}`}
              transform="rotate(-90 7 7)"
            />
          )}
        </>
      )}
    </svg>
  );
}

/** Signal bars lit up to `level` (1..3), a filled alert square for "urgent", a dash for 0. */
export function LevelGlyph({ level, className }: { level: 0 | 1 | 2 | 3 | "urgent"; className?: string }) {
  if (level === "urgent") {
    return (
      <svg viewBox="0 0 14 14" className={cn("size-3.5 shrink-0 text-(--priority-urgent)", className)} aria-hidden>
        <rect x="1" y="1" width="12" height="12" rx="3" fill="currentColor" />
        <path d="M7 3.8v4" stroke="var(--background)" strokeWidth="1.6" strokeLinecap="round" />
        <circle cx="7" cy="10.1" r="0.95" fill="var(--background)" />
      </svg>
    );
  }
  if (level === 0) {
    return (
      <svg viewBox="0 0 14 14" className={cn("text-subtle-foreground size-3.5 shrink-0", className)} aria-hidden>
        {[2.5, 6, 9.5].map((x) => (
          <rect key={x} x={x - 0.9} y="6.2" width="1.8" height="1.6" rx="0.5" fill="currentColor" />
        ))}
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 14 14" className={cn("text-muted-foreground size-3.5 shrink-0", className)} aria-hidden>
      {[0, 1, 2].map((i) => (
        <rect
          key={i}
          x={1.5 + i * 4}
          y={9 - i * 3}
          width="3"
          height={3 + i * 3}
          rx="0.8"
          fill="currentColor"
          opacity={i < level ? 1 : 0.25}
        />
      ))}
    </svg>
  );
}
