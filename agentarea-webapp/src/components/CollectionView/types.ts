import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

export type CollectionViewMode = "list" | "grid";

/** A small pill shown in the row meta cluster / card footer. */
export interface CollectionBadge {
  label: string;
  /** Hex colour → rendered as a colour-dot pill (the source pill in Skills). */
  color?: string;
  /** Optional leading glyph → rendered as a muted icon + label (the scope style). */
  icon?: LucideIcon;
}

/** A hover quick-action (favourite, duplicate, …). The first few render as
 *  buttons in the hover cluster; all of them appear in the ⋯ dropdown. */
export interface CollectionAction {
  icon: LucideIcon;
  /** Title / aria-label and the dropdown item text. */
  label: string;
  onClick: (e: React.MouseEvent) => void;
  /** e.g. a filled favourite star. */
  active?: boolean;
  /** Colour applied when `active` (e.g. "#d99a00"). */
  activeColor?: string;
  /** Hide from the hover button cluster (still shown in the ⋯ menu). */
  menuOnly?: boolean;
}

/**
 * Normalized shape every page adapts its domain item into. The CollectionView
 * renders rows/cards purely from this — it never sees the original type.
 */
export interface CollectionItem {
  id: string;
  /** A Lucide icon → tinted Tile, or any node (e.g. an <img> logo) → rendered
   *  inside the same bordered square. */
  icon: LucideIcon | ReactNode;
  /** Accent colour for the tile tint and the primary dot. */
  color: string;
  title: string;
  description?: string | null;
  /** Open target. `href` takes precedence over `onOpen`. */
  href?: string;
  onOpen?: () => void;
  /** Row: right-hand meta cluster. Card: footer pills. */
  badges?: CollectionBadge[];
  /** Row only: node rendered immediately after the title, before the
   *  description (e.g. inline type/Custom pills). Ignored by cards. */
  afterTitle?: ReactNode;
  /** Row only: override the title column width classes (e.g. a fixed
   *  `w-[200px] shrink-0` so following columns line up vertically). */
  titleClassName?: string;
  /** Card only: render the description on a single truncated line instead of
   *  the default two-line clamp (more compact cards). */
  compactDescription?: boolean;
  /** Row-only trailing node — cost, date, avatars, … Cards ignore it (use
   *  `cardFooter` for card-specific content). */
  meta?: ReactNode;
  /** Hover quick-actions. Empty/undefined ⇒ only the diagonal open-arrow shows. */
  actions?: CollectionAction[];

  /** Card only: node shown at the right end of the card header row (e.g. a
   *  status dot). Ignored by rows. */
  headerAside?: ReactNode;
  /** Card only: omit the description block entirely (compact cards). */
  hideDescription?: boolean;
  /** Drop the leading glyph tile (both row and card) so the title leads
   *  directly — e.g. tasks, which carry no icon of their own. */
  hideIcon?: boolean;
  /** Card only: custom lower content, replacing the default badges + meta
   *  footer (e.g. a model line over a tasks/tools row). Ignored by rows. */
  cardFooter?: ReactNode;
}

export interface CollectionGroup {
  key: string;
  label: string;
  /** Colour-dot beside the group label. */
  color: string;
  items: CollectionItem[];
}

/** A titled block on a page that renders multiple independent lists. */
export interface CollectionSection {
  id: string;
  title?: ReactNode;
  /** Provide exactly one of `items` / `groups`. */
  items?: CollectionItem[];
  groups?: CollectionGroup[];
  emptyState?: ReactNode;
}

export interface CollectionViewProps {
  view: CollectionViewMode;
  /** Provide exactly one of `items` / `groups` / `sections`. */
  items?: CollectionItem[];
  groups?: CollectionGroup[];
  sections?: CollectionSection[];

  isLoading?: boolean;
  /** Truthy ⇒ render the error state with this node as the message. */
  error?: ReactNode;
  /** Shown when the resolved list is empty. The caller chooses the copy
   *  (e.g. "no items yet" vs "nothing matches your search"). */
  emptyState?: ReactNode;

  /** Minimum grid card width in px (auto-fill). Default 264. */
  gridMinWidth?: number;
  /** Wrap in a `.collection-cq` size container so columns drop responsively.
   *  Default true. */
  containerQuery?: boolean;
  /** Collapsible sticky group headers. Default true. */
  collapsibleGroups?: boolean;
  /** Extra classes on the grid container (e.g. padding when self-managed). */
  gridClassName?: string;
  /** List view only: cancel the surrounding `px-4` page gutter so rows run
   *  edge-to-edge of the container (matches the dense Linear list look). Use
   *  when the component sits inside a ContentBlock body (px-4). */
  bleed?: boolean;
  className?: string;
}
