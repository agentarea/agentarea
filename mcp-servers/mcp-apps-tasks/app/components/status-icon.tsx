import { StatusGlyph } from "@kit/components/glyphs";
import type { Status } from "@shared/tasks";
import { STATUS_META } from "@/lib/meta";

/** The workflow glyph: the ring fills as the issue moves towards done. */
export function StatusIcon({ status, className }: { status: Status; className?: string }) {
  const { color, glyph, progress } = STATUS_META[status];
  return <StatusGlyph shape={glyph} progress={progress} color={color} className={className} />;
}
