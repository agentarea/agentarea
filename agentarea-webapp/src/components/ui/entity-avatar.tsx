import * as React from "react";
import { avatarHueStyle, type AvatarHue } from "@/lib/avatar-hue";
import { cn } from "@/lib/utils";

/** Default background for the `soft` chip when no `color` is given. */
const SOFT_DEFAULT_COLOR = "#71717a";

/** Below this the 1px hatch stripe is sub-pixel noise rather than texture. */
const HATCH_FROM = 28;

/** Below this a squircle and a plain radius differ by less than half a pixel. */
const SQUIRCLE_FROM = 40;

type BaseProps = {
  /** Square side length in px. Font, glyph and radius all scale from this. */
  size?: number;
  /** Initials or short label, shown when there is no image or icon. */
  text?: string;
  /** Icon element, shown when there is no image. Sized to the tile. */
  icon?: React.ReactNode;
  /**
   * How much of the tile the icon fills. The 0.5 default suits a stroke glyph.
   * A brand logo wants ~0.68: it is optically denser, it usually carries its
   * own background plate, and at half the tile it reads as a small square
   * sitting inside a bigger one rather than as a framed mark. Note the hue goes
   * inert in that case — a logo does not inherit `currentColor`, so the tile is
   * just a neutral plate and the brand does the identifying.
   */
  iconScale?: number;
  /** Image URL. When set it fills the tile (object-cover, centred). */
  src?: string;
  alt?: string;
  /** Corner radius in px. Defaults to ~29.5% of `size`. */
  rounded?: number;
  /** Override the size-driven hatch decision. */
  hatch?: boolean;
  /** Set when the name is already rendered next to the tile. */
  "aria-hidden"?: boolean;
  className?: string;
};

type IdentityProps = BaseProps & {
  /**
   * `graphite` — neutral tile, glyph carries the hue. For things: agents,
   * catalog entries, connections.
   * `pigment` — hue fills the tile, mark stays white. For people.
   */
  variant?: "graphite" | "pigment";
  hue: AvatarHue;
  color?: never;
};

type SoftProps = BaseProps & {
  /** A flat, borderless tint — for status and category chips, not identity. */
  variant: "soft";
  color?: string;
  hue?: never;
};

export type EntityAvatarProps = IdentityProps | SoftProps;

/**
 * The square tile every generated avatar is drawn on. Renders, in priority
 * order: an image, an icon, or text initials.
 *
 * Identity avatars get their depth from simulated light rather than from
 * saturation — the gradient, lit edge, hairline and shadow all live in
 * `globals.css` under `.avatar-graphite` / `.avatar-pigment`, so this component
 * only decides size, shape and what goes in the middle.
 */
export function EntityAvatar(props: EntityAvatarProps) {
  const {
    size = 28,
    text,
    icon,
    iconScale = 0.5,
    src,
    alt,
    rounded,
    hatch,
    className,
    "aria-hidden": ariaHidden,
  } = props;

  const soft = props.variant === "soft";
  const variant = props.variant ?? "graphite";
  const radius = rounded ?? Math.round(size * 0.295);
  const hatched = (hatch ?? size >= HATCH_FROM) && !soft;

  const surface: React.CSSProperties = (() => {
    if (props.variant === "soft") {
      const color = props.color ?? SOFT_DEFAULT_COLOR;
      return {
        color,
        backgroundColor: `color-mix(in srgb, ${color} 8%, transparent)`,
      };
    }
    return avatarHueStyle(props.hue);
  })();

  return (
    <span
      aria-hidden={ariaHidden}
      className={cn(
        "avatar-tile overflow-hidden",
        variant === "graphite" && "avatar-graphite",
        variant === "pigment" && "avatar-pigment",
        hatched && "avatar-hatch",
        !soft && size >= SQUIRCLE_FROM && "avatar-squircle",
        className
      )}
      style={{ width: size, height: size, borderRadius: radius, ...surface }}
    >
      {src ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={src}
          alt={alt}
          className="absolute inset-0 z-[2] h-full w-full object-cover"
        />
      ) : icon ? (
        <span
          className="relative z-[2] inline-flex items-center justify-center [&>svg]:h-full [&>svg]:w-full"
          style={{
            width: Math.round(size * iconScale),
            height: Math.round(size * iconScale),
          }}
        >
          {icon}
        </span>
      ) : text ? (
        <span
          className="relative z-[2] font-semibold uppercase leading-none tracking-[-0.02em]"
          style={{ fontSize: Math.round(size * 0.38) }}
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
