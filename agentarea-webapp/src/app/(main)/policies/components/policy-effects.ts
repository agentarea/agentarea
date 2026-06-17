import type { PolicyEffect } from "@/types/policies";

// Shared effect tokens. Kept deliberately restrained to match the Skills page:
// a single small status dot carries the only colour; chips stay neutral
// (muted surface + foreground text) so the list reads calm, not rainbow.
export const EFFECT_STYLES: Record<
  PolicyEffect,
  { label: string; dot: string; chip: string }
> = {
  allow: {
    label: "Allow",
    dot: "bg-emerald-500/70",
    chip: "bg-muted text-foreground/70",
  },
  cap: {
    label: "Cap",
    dot: "bg-sky-500/70",
    chip: "bg-muted text-foreground/70",
  },
  approval: {
    label: "Approval",
    dot: "bg-amber-500/70",
    chip: "bg-muted text-foreground/70",
  },
  deny: {
    label: "Deny",
    dot: "bg-rose-500/70",
    chip: "bg-muted text-foreground/70",
  },
  safety: {
    label: "Safety",
    dot: "bg-zinc-400",
    chip: "bg-muted text-foreground/70",
  },
};
