import type { GlyphShape } from "@kit/components/glyphs";
import type { Tone } from "@kit/components/chip";
import type { ActivityType, DealStatus } from "@shared/crm";
import type { Stage } from "@shared/schema";
import { CalendarClock, ListTodo, Mail, Phone, StickyNote, type LucideIcon } from "lucide-react";

export const ACTIVITY_META: Record<ActivityType, { label: string; icon: LucideIcon; placeholder: string }> = {
  call: { label: "Call", icon: Phone, placeholder: "Follow-up call on the proposal" },
  email: { label: "Email", icon: Mail, placeholder: "Send revised pricing" },
  meeting: { label: "Meeting", icon: CalendarClock, placeholder: "Demo for the operations team" },
  task: { label: "Task", icon: ListTodo, placeholder: "Prepare the contract draft" },
  note: { label: "Note", icon: StickyNote, placeholder: "Budget confirmed for Q4" },
};

export const STATUS_META: Record<DealStatus, { label: string; tone: Tone }> = {
  open: { label: "Open", tone: "info" },
  won: { label: "Won", tone: "success" },
  lost: { label: "Lost", tone: "neutral" },
};

/** A stage as a progress glyph: the ring fills with its win probability; won is a check, lost a cross. */
export function stageGlyph(stage: Pick<Stage, "probability" | "outcome">): {
  shape: GlyphShape;
  progress?: number;
  color: string;
} {
  if (stage.outcome === "won") return { shape: "done", color: "var(--complete)" };
  if (stage.outcome === "lost") return { shape: "canceled", color: "var(--subtle-foreground)" };
  const color =
    stage.probability >= 0.7
      ? "var(--success)"
      : stage.probability >= 0.25
        ? "var(--progress)"
        : "var(--muted-foreground)";
  return { shape: "open", progress: stage.probability, color };
}
