import {
  CheckCircle2,
  ShieldCheck,
  UserCheck,
  Wallet,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import type { PolicyEffect } from "@/types/policies";

// Shared effect tokens. Keep them neutral; policy type is carried by the icon,
// not by a separate colour system.
export const EFFECT_STYLES: Record<
  PolicyEffect,
  { label: string; icon: LucideIcon; chip: string }
> = {
  allow: {
    label: "Allow",
    icon: CheckCircle2,
    chip: "bg-muted text-foreground/70",
  },
  cap: {
    label: "Budget",
    icon: Wallet,
    chip: "bg-muted text-foreground/70",
  },
  approval: {
    label: "Approval",
    icon: UserCheck,
    chip: "bg-muted text-foreground/70",
  },
  deny: {
    label: "Deny",
    icon: Wrench,
    chip: "bg-muted text-foreground/70",
  },
  safety: {
    label: "Safety",
    icon: ShieldCheck,
    chip: "bg-muted text-foreground/70",
  },
};
