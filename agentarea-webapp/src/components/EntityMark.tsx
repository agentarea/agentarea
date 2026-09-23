"use client";

import { useEffect, useRef, useState } from "react";
import { avatarHueStyle, deterministicHue } from "@/lib/avatar-hue";
import { EntityIcon } from "@/lib/entity-icons";
import { BRAND_MARKS, type EntityIdentity } from "@/lib/entity-identity";
import { cn } from "@/lib/utils";

interface EntityMarkProps {
  identity: EntityIdentity;
  /** Sizing/shape of the mark box, e.g. `h-8 w-8 rounded-md`. */
  className?: string;
  /** Extra classes for the glyph fallback only (colour, mostly). */
  glyphClassName?: string;
  /**
   * Append the kind's own mark (`/mcp.svg`) to the source chain. On by
   * default: one connection wearing the MCP logo reads as "an MCP server".
   * A *gallery* of them does not — every unbranded entry would look the same,
   * which is what the initials exist to prevent — so the catalog turns it off
   * and labels the protocol next to the name instead.
   */
  brandFallback?: boolean;
}

/**
 * The visual identity of one entity, resolved at render time: the first logo
 * that loads, else domain initials, else the kind's glyph. Every surface that
 * shows a connection — graph nodes, cards, tool chips — draws it through here,
 * so a connection looks the same wherever it appears.
 *
 * Logos are `<img>`, not `next/image`, on purpose: these URLs point at
 * customer-controlled hosts, and next/image would fetch them from our server
 * instead of the viewer's browser. `onError` is what walks the chain, so the
 * element has to stay a plain image.
 */
export default function EntityMark({
  identity,
  className,
  glyphClassName,
  brandFallback = true,
}: EntityMarkProps) {
  const { kind, initials } = identity;
  const brand = brandFallback ? BRAND_MARKS[kind] : undefined;
  const sources =
    brand && !identity.sources.includes(brand)
      ? [...identity.sources, brand]
      : identity.sources;

  const [failed, setFailed] = useState(0);
  const chain = sources.join("|");
  useEffect(() => setFailed(0), [chain]);

  const src = sources[failed];
  const imgRef = useRef<HTMLImageElement | null>(null);
  // An image that finished failing before hydration never fires `onError` --
  // React attaches the handler after the browser is done with the request. The
  // server renders these marks, and a guessed favicon 404s in milliseconds, so
  // without this check the first candidate's broken image is what stays on
  // screen. `complete` with no intrinsic size is what a failed load looks like
  // after the fact.
  useEffect(() => {
    const img = imgRef.current;
    if (img?.complete && img.naturalWidth === 0) {
      setFailed((count) => count + 1);
    }
  }, [src]);

  if (src) {
    return (
      // eslint-disable-next-line @next/next/no-img-element -- see note above
      <img
        ref={imgRef}
        src={src}
        alt=""
        aria-hidden
        onError={() => setFailed((count) => count + 1)}
        className={cn("object-contain", className)}
      />
    );
  }

  if (initials) {
    return (
      <span
        aria-hidden
        style={avatarHueStyle(deterministicHue(chain || initials))}
        className={cn(
          "avatar-tile avatar-graphite text-[8px] font-semibold leading-none tracking-[-0.02em]",
          className
        )}
      >
        {initials}
      </span>
    );
  }

  return <EntityIcon kind={kind} className={cn(className, glyphClassName)} />;
}
