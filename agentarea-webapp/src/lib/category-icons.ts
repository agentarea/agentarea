import {
  Activity,
  Banknote,
  ChartNoAxesColumn,
  CircleDashed,
  Code2,
  FileText,
  FlaskConical,
  Globe,
  LifeBuoy,
  ListChecks,
  Megaphone,
  Microscope,
  Package,
  Palette,
  Rocket,
  Search,
  Shield,
  Tag,
  TrendingUp,
  Users,
  type LucideIcon,
} from "lucide-react";
import { ENTITY_ICONS } from "@/lib/entity-icons";

/**
 * Collapse a category to the form the icon map is keyed by.
 *
 * The catalog's categories arrive from three sources that never agreed on a
 * spelling: the MCP registry title-cases and joins with ampersands
 * ("Data & Analytics"), skills and bundles use bare lowercase words ("data").
 * Keying on the raw string would need an entry per spelling, and would miss
 * the next source's.
 */
function normalize(category: string): string {
  return category
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

/**
 * Icon per catalog category.
 *
 * Keyed by the normalized form, so one entry serves every spelling of the same
 * concept. Several categories are the same idea at different granularity --
 * "development", "engineering" and "devops" all describe writing and shipping
 * software -- and they deliberately share an icon rather than reaching for a
 * distinct-but-meaningless one.
 */
const CATEGORY_ICONS: Record<string, LucideIcon> = {
  "ai search": Search,
  agent: ENTITY_ICONS.agent,
  analysis: ChartNoAxesColumn,
  communication: ENTITY_ICONS.client,
  creative: Palette,
  data: ChartNoAxesColumn,
  "data analytics": ChartNoAxesColumn,
  design: Palette,
  development: Code2,
  devops: Rocket,
  documents: FileText,
  engineering: Code2,
  finance: Banknote,
  "finance commerce": Banknote,
  hr: Users,
  marketing: Megaphone,
  operations: Activity,
  product: Package,
  productivity: ListChecks,
  research: Microscope,
  sales: TrendingUp,
  "sales crm": TrendingUp,
  security: Shield,
  support: LifeBuoy,
  testing: FlaskConical,
  "web hosting": Globe,

  // Not a topic — what a source writes when it could not classify an entry.
  // Its own icon so the sidebar does not present it as a peer of the rest.
  other: CircleDashed,
};

/**
 * The icon a category renders with, or one neutral tag when it is unknown.
 *
 * The fallback is deliberately constant rather than derived from the string.
 * Hashing a name onto the icon set would dress every unmapped category in a
 * confident, wrong symbol, and quietly restyle it whenever a source renames
 * the category. A plain tag reads as "no icon for this yet", which is true.
 */
export function getCategoryIcon(category: string | null | undefined): LucideIcon {
  if (!category) return Tag;
  return CATEGORY_ICONS[normalize(category)] ?? Tag;
}
