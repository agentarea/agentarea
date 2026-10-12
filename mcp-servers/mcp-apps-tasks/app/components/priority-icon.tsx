import { LevelGlyph } from "@kit/components/glyphs";
import type { Priority } from "@shared/tasks";

const LEVEL = { urgent: "urgent", high: 3, medium: 2, low: 1, none: 0 } as const;

export function PriorityIcon({ priority, className }: { priority: Priority; className?: string }) {
  return <LevelGlyph level={LEVEL[priority]} className={className} />;
}
