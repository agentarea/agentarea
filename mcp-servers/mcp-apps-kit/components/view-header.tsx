import { LayoutGrid, type LucideIcon, RefreshCw, Rows3, Search } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "../lib/utils";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { Tabs, TabsList, TabsTrigger } from "../ui/tabs";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";

const WIDTHS = { wide: "max-w-[1800px]", detail: "max-w-[1120px]" };

/** The page frame every view sits in: the same width, gutters and vertical rhythm. */
export function Page({
  width = "wide",
  className,
  children,
}: {
  width?: keyof typeof WIDTHS;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={cn("mx-auto flex w-full flex-col gap-4 p-3 sm:p-5", WIDTHS[width], className)}>{children}</div>
  );
}

/** The view's title row: an app tile, a title, one line of context, and the actions on the right. */
export function ViewHeader({
  icon: Icon,
  title,
  subtitle,
  actions,
}: {
  icon: LucideIcon;
  title: ReactNode;
  subtitle: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <div className="flex min-w-0 items-center gap-2.5">
        <div className="bg-primary text-primary-foreground flex size-8 shrink-0 items-center justify-center rounded-lg shadow-xs">
          <Icon className="size-4" strokeWidth={2.25} />
        </div>
        <div className="min-w-0">
          <h1 className="truncate text-[15px] leading-tight font-semibold tracking-tight">{title}</h1>
          <p className="text-muted-foreground tabular truncate text-xs">{subtitle}</p>
        </div>
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}

/** Reloads the view from its MCP server; spins while it does. */
export function RefreshButton({
  busy,
  onClick,
  compact,
  className,
  label = "Reload from the MCP server",
}: {
  busy?: boolean;
  onClick: () => void;
  compact?: boolean;
  className?: string;
  label?: string;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant="outline"
          size="icon"
          className={cn(compact ? "size-7" : "size-8", className)}
          aria-label="Refresh"
          onClick={onClick}
          disabled={busy}
        >
          <RefreshCw className={cn(compact && "size-3.5", busy && "animate-spin")} />
        </Button>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

export type LayoutMode = "board" | "list";

/** Board / List switch. */
export function LayoutTabs({ value, onChange }: { value: LayoutMode; onChange: (mode: LayoutMode) => void }) {
  return (
    <Tabs value={value} onValueChange={(next) => onChange(next as LayoutMode)}>
      <TabsList aria-label="Layout">
        <TabsTrigger value="board" aria-label="Board">
          <LayoutGrid />
          <span className="hidden sm:inline">Board</span>
        </TabsTrigger>
        <TabsTrigger value="list" aria-label="List">
          <Rows3 />
          <span className="hidden sm:inline">List</span>
        </TabsTrigger>
      </TabsList>
    </Tabs>
  );
}

/** The row of filters under the header. */
export function FilterRow({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn("flex flex-wrap items-center gap-2", className)}>{children}</div>;
}

/** A text filter with a search glyph. */
export function SearchField({
  value,
  onChange,
  placeholder,
  label,
  className,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  label: string;
  className?: string;
}) {
  return (
    <div className={cn("relative min-w-[160px] flex-[2]", className)}>
      <Search className="text-subtle-foreground pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2" />
      <Input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        aria-label={label}
        className="pl-7"
      />
    </div>
  );
}

/** "Platform › OPS-10": where a detail view sits, each step a link back. */
export function Breadcrumb({ children }: { children: ReactNode }) {
  return (
    <nav className="text-muted-foreground flex min-w-0 items-center gap-1 text-xs" aria-label="Breadcrumb">
      {children}
    </nav>
  );
}
