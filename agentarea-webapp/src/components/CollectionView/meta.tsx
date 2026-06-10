import { isValidElement, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { Bot, type LucideIcon } from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

/** Shared accent colour for the agent chip (the Bot tile tint). */
export const AGENT_COLOR = "#5e6ad2";

/**
 * Status indicator — a small colour dot followed by a colour-matched label
 * (e.g. "● Active"). The single shared status badge reused across every
 * collection page (Tasks, Agents, Connections, Models). Purely presentational:
 * each page maps its own domain status into a `color` + `label`; the rendering
 * stays identical everywhere.
 */
export function StatusDot({
  color,
  label,
  dotOnly,
  pulse,
  tooltip,
  className,
}: {
  color: string;
  label: ReactNode;
  /** Render only the dot (label hidden) — for dense / icon-only contexts. */
  dotOnly?: boolean;
  /** Animate the dot (e.g. a running task). */
  pulse?: boolean;
  /** When provided, wrap in a tooltip showing this content. */
  tooltip?: ReactNode;
  className?: string;
}) {
  const content = (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap text-[11.5px] font-normal",
        className
      )}
      style={{ color: dotOnly ? undefined : color }}
    >
      <span
        className={cn(
          "h-[7px] w-[7px] shrink-0 rounded-full",
          pulse && "motion-safe:animate-pulse"
        )}
        style={{ backgroundColor: color }}
      />
      {!dotOnly && label}
    </span>
  );

  if (tooltip == null) return content;
  return (
    <Tooltip>
      <TooltipTrigger asChild>{content}</TooltipTrigger>
      <TooltipContent>{tooltip}</TooltipContent>
    </Tooltip>
  );
}

/**
 * Brand glyph tile — a softly colour-tinted square (13% colour over the
 * surface) with a matching 26% border. Accepts either a Lucide icon (rendered
 * in the accent colour) or an arbitrary node (e.g. an <img> provider logo),
 * which is rendered inside the same bordered square.
 */
export function Tile({
  color,
  icon,
  variant = "row",
  size,
  fill,
}: {
  color: string;
  icon: LucideIcon | ReactNode;
  variant?: "row" | "card";
  /** Override the preset box size (px). Radius/glyph scale to match. */
  size?: number;
  /** The icon is a self-contained mark (a solid logo / initials block) that
   *  should fill the whole tile: drop the colour tint + border and let the icon
   *  bleed edge-to-edge (pass it `h-full w-full`). The tile only supplies the
   *  fixed box size + rounded clip. */
  fill?: boolean;
}) {
  const isCard = variant === "card";
  const box = size ?? (isCard ? 30 : 22);
  const radius = size ? Math.round(size * 0.27) : isCard ? 8 : 6;
  const glyph = size ? Math.round(size * 0.6) : isCard ? 17 : 13;

  // A bare Lucide component (function/exotic object) → render tinted.
  const isComponent =
    typeof icon === "function" ||
    (typeof icon === "object" && icon !== null && !isValidElement(icon));
  const IconComponent = isComponent ? (icon as LucideIcon) : null;

  return (
    <span
      className={cn(
        "relative flex shrink-0 items-center justify-center overflow-hidden",
        !fill && "border"
      )}
      style={{
        width: box,
        height: box,
        borderRadius: radius,
        ...(fill
          ? {}
          : {
              color,
              background: `color-mix(in srgb, ${color} 13%, var(--tile-base))`,
              borderColor: `color-mix(in srgb, ${color} 26%, var(--tile-base))`,
            }),
      }}
    >
      {IconComponent ? (
        <IconComponent style={{ width: glyph, height: glyph }} strokeWidth={1.9} />
      ) : (
        (icon as ReactNode)
      )}
    </span>
  );
}

/** Compact relative age, e.g. "today", "3d", "2w", "5mo", "1y". Pass the
 *  `Collection` translator `t` to localize; omit it for the plain English form. */
export function shortAge(
  iso: string | null | undefined,
  t?: (key: string, values?: Record<string, string | number>) => string
): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const days = Math.floor((Date.now() - then) / 86_400_000);
  if (!t) {
    if (days < 1) return "today";
    if (days < 7) return `${days}d`;
    if (days < 30) return `${Math.floor(days / 7)}w`;
    if (days < 365) return `${Math.floor(days / 30)}mo`;
    return `${Math.floor(days / 365)}y`;
  }
  if (days < 1) return t("ageToday");
  if (days < 7) return t("ageDays", { n: days });
  if (days < 30) return t("ageWeeks", { n: Math.floor(days / 7) });
  if (days < 365) return t("ageMonths", { n: Math.floor(days / 30) });
  return t("ageYears", { n: Math.floor(days / 365) });
}

/**
 * Agent chip — a Bot tile + agent name, the single shared representation of an
 * agent across collection rows/cards (Tasks, Automation, …). The hover tooltip
 * (showing the full name) is on by default; pass `tooltip={false}` where the
 * name can't truncate (e.g. roomy card footers) or there's no TooltipProvider.
 */
export function AgentChip({
  name,
  size = 18,
  tooltip = true,
  className,
}: {
  name: string | null | undefined;
  size?: number;
  tooltip?: boolean;
  className?: string;
}) {
  const t = useTranslations("Collection");
  const display = name || t("unknownAgent");
  const content = (
    <span
      className={cn(
        "inline-flex min-w-0 items-center gap-2 text-[12.5px] text-foreground/80",
        className
      )}
    >
      <Tile color={AGENT_COLOR} icon={Bot} size={size} />
      <span className="truncate">{display}</span>
    </span>
  );
  if (!tooltip) return content;
  return (
    <Tooltip>
      <TooltipTrigger asChild>{content}</TooltipTrigger>
      <TooltipContent>{display}</TooltipContent>
    </Tooltip>
  );
}
