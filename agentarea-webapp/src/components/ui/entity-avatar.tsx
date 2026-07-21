import * as React from "react";
import { cn } from "@/lib/utils";

/** Default background when no `color` is provided. */
const DEFAULT_COLOR = "#3b5bdb";

/** Diagonal line texture drawn on top of the solid color. */
const LINE_TEXTURE =
  "repeating-linear-gradient(135deg, rgba(255,255,255,0.16) 0px, rgba(255,255,255,0.16) 1px, transparent 1px, transparent 7px)";

export type EntityAvatarProps = {
  /** Square side length in px. Font/icon/radius scale from this. */
  size?: number;
  /** Background color. Defaults to blue. */
  color?: string;
  /** Initials or short label shown when there's no image/icon. */
  text?: string;
  /** Icon element shown when there's no image. Sized to the tile automatically. */
  icon?: React.ReactNode;
  /** Image URL. When set, it fills the tile (object-cover, centered). */
  src?: string;
  alt?: string;
  /** Toggle the diagonal line texture. Defaults to true. */
  lines?: boolean;
  /** Corner radius in px. Defaults to ~20% of `size` (lightly rounded square). */
  rounded?: number;
  /**
   * "solid" (default): white text/icon on a fully-colored tile.
   * "soft": colored text/icon on a soft, borderless tint of `color`.
   */
  variant?: "solid" | "soft";
  className?: string;
};

/**
 * Reusable square avatar/tile. Renders, in priority order: an image (stretched
 * to fill), an icon, or text initials — over a colored, line-textured
 * background. Handy for users, agents, skills, workspaces, etc.
 */
export function EntityAvatar({
  size = 28,
  color = DEFAULT_COLOR,
  text,
  icon,
  src,
  alt,
  lines = true,
  rounded,
  variant = "solid",
  className,
}: EntityAvatarProps) {
  const radius = rounded ?? Math.round(size * 0.2);
  const soft = variant === "soft";

  return (
    <span
      className={cn(
        "relative inline-flex shrink-0 items-center justify-center overflow-hidden",
        !soft && "text-white",
        className
      )}
      style={{
        width: size,
        height: size,
        borderRadius: radius,
        color: soft ? color : undefined,
        backgroundColor: soft
          ? `color-mix(in srgb, ${color} 8%, transparent)`
          : color,
        backgroundImage: lines && !soft ? LINE_TEXTURE : undefined,
      }}
    >
      {src ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={src}
          alt={alt}
          className="absolute inset-0 h-full w-full object-cover"
        />
      ) : icon ? (
        <span
          className="inline-flex items-center justify-center [&>svg]:h-full [&>svg]:w-full"
          style={{ width: Math.round(size * 0.5), height: Math.round(size * 0.5) }}
        >
          {icon}
        </span>
      ) : text ? (
        <span
          className="font-semibold uppercase leading-none"
          style={{ fontSize: Math.round(size * 0.4) }}
        >
          {text}
        </span>
      ) : null}
    </span>
  );
}

/** First letters of the first and last words of a name, e.g. "Julia Astapenko" → "JA". */
export function nameInitials(name?: string): string {
  if (!name) return "";
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "";
  if (words.length === 1) return words[0].charAt(0).toUpperCase();
  return (
    words[0].charAt(0) + words[words.length - 1].charAt(0)
  ).toUpperCase();
}
