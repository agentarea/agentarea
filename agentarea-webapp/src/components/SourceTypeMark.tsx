import EntityMark from "@/components/EntityMark";
import { EntityAvatar } from "@/components/ui/entity-avatar";
import { deterministicHue } from "@/lib/avatar-hue";
import { sourceTypeIdentity } from "@/lib/entity-identity";
import type { SourceType } from "@/lib/sourceTypes";

/**
 * Where events come from, drawn from the catalog entry: its artwork, else the
 * stream glyph. `inline` is the bare mark for a select row or a chip; the
 * default is the graphite tile hued by the slug, for list rows.
 */
export default function SourceTypeMark({
  type,
  slug,
  size = 28,
  inline = false,
  className = "h-4 w-4",
}: {
  type: SourceType | null | undefined;
  /** The source's slug, when its entry may be missing from the catalog. */
  slug?: string | null;
  size?: number;
  inline?: boolean;
  className?: string;
}) {
  const mark = (
    <EntityMark
      identity={sourceTypeIdentity(type)}
      className={inline ? className : "h-full w-full"}
      glyphClassName="text-muted-foreground"
    />
  );
  if (inline) return mark;
  return (
    <EntityAvatar
      size={size}
      hue={deterministicHue(type?.slug ?? slug ?? "stream")}
      icon={mark}
      iconScale={type?.icon_url ? 0.68 : 0.5}
      aria-hidden
    />
  );
}
