import type { PersonStatus, ReplyClass, SignalStrength, SignalType } from "@shared/outreach";
import {
  Banknote,
  Briefcase,
  Flame,
  Globe,
  Layers,
  type LucideIcon,
  Snowflake,
  Star,
  Sun,
  UserPlus,
} from "lucide-react";

export const SIGNAL_META: Record<SignalType, { label: string; icon: LucideIcon; tile: string }> = {
  funding_round: { label: "Funding round", icon: Banknote, tile: "bg-success-surface text-success" },
  hiring_surge: { label: "Hiring surge", icon: Briefcase, tile: "bg-info-surface text-info" },
  new_executive: { label: "New executive", icon: UserPlus, tile: "bg-[color-mix(in_oklab,var(--reply-referral)_14%,transparent)] text-(--reply-referral)" },
  tech_stack_change: { label: "Tech stack change", icon: Layers, tile: "bg-warning-surface text-warning" },
  website_intent: { label: "Website intent", icon: Globe, tile: "bg-danger-surface text-danger" },
  g2_research: { label: "G2 research", icon: Star, tile: "bg-secondary text-foreground" },
};

export const STRENGTH_META: Record<SignalStrength, { label: string; icon: LucideIcon; variant: "danger" | "warning" | "info" }> = {
  hot: { label: "Hot", icon: Flame, variant: "danger" },
  warm: { label: "Warm", icon: Sun, variant: "warning" },
  cold: { label: "Cold", icon: Snowflake, variant: "info" },
};

export const REPLY_META: Record<ReplyClass, { label: string; color: string }> = {
  interested: { label: "Interested", color: "var(--reply-interested)" },
  meeting_booked: { label: "Meeting booked", color: "var(--reply-meeting_booked)" },
  referral: { label: "Referral", color: "var(--reply-referral)" },
  not_now: { label: "Not now", color: "var(--reply-not_now)" },
  objection: { label: "Objection", color: "var(--reply-objection)" },
  out_of_office: { label: "Out of office", color: "var(--reply-out_of_office)" },
  unsubscribe: { label: "Unsubscribe", color: "var(--reply-unsubscribe)" },
};

export const STATUS_META: Record<
  PersonStatus,
  { label: string; variant: "muted" | "info" | "secondary" | "success" | "danger" | "warning" }
> = {
  scheduled: { label: "Scheduled", variant: "secondary" },
  in_sequence: { label: "In sequence", variant: "info" },
  finished: { label: "No reply", variant: "muted" },
  replied: { label: "Replied", variant: "warning" },
  meeting: { label: "Meeting booked", variant: "success" },
  unsubscribed: { label: "Unsubscribed", variant: "danger" },
};
