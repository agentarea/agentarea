import type { CSSProperties } from "react";

/**
 * The one colour ramp every generated avatar draws from — agents, people,
 * catalog entries.
 *
 * Only the hue varies. Lightness and chroma are pinned in `globals.css`
 * (`.avatar-graphite` / `.avatar-pigment`), so no swatch is louder than its
 * neighbour and the same agent keeps its colour when the theme flips. The
 * previous ramp reused `--chart-1..5` + `--primary` + `--accent`: stock shadcn
 * chart colours whose lightness ran from 0.38 to 0.83, whose chroma varied
 * fourfold, which swapped hues wholesale between light and dark, and whose last
 * two entries were the same blue as the UI's own buttons.
 *
 * Names, not degrees, are what a stored preference would hold: `azure` survives
 * a palette retune, `252` does not.
 */
export const AVATAR_HUES = {
  azure: 252,
  indigo: 278,
  violet: 312,
  rose: 350,
  coral: 28,
  amber: 62,
  emerald: 152,
  teal: 196,
} as const;

export type AvatarHue = keyof typeof AVATAR_HUES;

export const AVATAR_HUE_NAMES = Object.keys(AVATAR_HUES) as AvatarHue[];

export function isAvatarHue(value: unknown): value is AvatarHue {
  return typeof value === "string" && value in AVATAR_HUES;
}

/**
 * FNV-1a with a murmur3 finaliser. The avalanche step matters: the ramp is
 * eight long, so a plain djb2 would pick a swatch from three low bits alone and
 * hand sequential ids (`agent-1`, `agent-2`) the same colour.
 */
function hash(seed: string): number {
  let h = 2166136261;
  for (let i = 0; i < seed.length; i++) {
    h ^= seed.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  h ^= h >>> 16;
  h = Math.imul(h, 2246822507);
  h ^= h >>> 13;
  return h >>> 0;
}

/** Stable hue for anything with an id but no chosen colour. */
export function deterministicHue(seed: string): AvatarHue {
  return AVATAR_HUE_NAMES[hash(seed) % AVATAR_HUE_NAMES.length];
}

/** Hands the hue to CSS, which is the only part of the ramp that varies. */
export function avatarHueStyle(hue: AvatarHue): CSSProperties {
  return { "--avatar-hue": String(AVATAR_HUES[hue]) } as CSSProperties;
}
