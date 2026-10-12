import type { Direction } from "@shared/books";
import type { Ledger, LedgerFilters } from "@shared/schema";
import { Chip } from "@kit/components/chip";
import { FilterRow, SearchField } from "@kit/components/view-header";
import { Inbox, X } from "lucide-react";
import { Button } from "@kit/ui/button";
import { Input } from "@kit/ui/input";
import { NativeSelect } from "@kit/ui/native-select";
import { Tabs, TabsList, TabsTrigger } from "@kit/ui/tabs";

export type FilterState = {
  text: string;
  account: string;
  /** A category id, "uncategorized", or "" for all. */
  category: string;
  counterparty: string;
  direction: Direction | "";
  reconciled: "" | "yes" | "no";
  from: string;
  to: string;
};

export const EMPTY_FILTERS: FilterState = {
  text: "",
  account: "",
  category: "",
  counterparty: "",
  direction: "",
  reconciled: "",
  from: "",
  to: "",
};

export const fromLedgerFilters = (f: LedgerFilters): FilterState => ({
  text: f.text ?? "",
  account: f.account ?? "",
  category: f.uncategorized ? "uncategorized" : (f.category ?? ""),
  counterparty: f.counterparty ?? "",
  direction: f.direction ?? "",
  reconciled: f.reconciled === null ? "" : f.reconciled ? "yes" : "no",
  from: f.from ?? "",
  to: f.to ?? "",
});

export function toolArgs(f: FilterState): Record<string, unknown> {
  return {
    ...(f.text.trim() ? { text: f.text.trim() } : {}),
    ...(f.account ? { account: f.account } : {}),
    ...(f.category === "uncategorized" ? { uncategorized: true } : f.category ? { category: f.category } : {}),
    ...(f.counterparty ? { counterparty: f.counterparty } : {}),
    ...(f.direction ? { direction: f.direction } : {}),
    ...(f.reconciled ? { reconciled: f.reconciled === "yes" } : {}),
    ...(f.from ? { from: f.from } : {}),
    ...(f.to ? { to: f.to } : {}),
  };
}

export function FilterBar({
  ledger,
  filters,
  onChange,
}: {
  ledger: Ledger;
  filters: FilterState;
  onChange: (next: FilterState) => void;
}) {
  const set = <K extends keyof FilterState>(key: K, value: FilterState[K]) => onChange({ ...filters, [key]: value });
  const reviewing = filters.category === "uncategorized";
  const active = JSON.stringify(filters) !== JSON.stringify(EMPTY_FILTERS);

  return (
    <div className="flex flex-col gap-2">
      <FilterRow>
        <SearchField
          value={filters.text}
          onChange={(text) => set("text", text)}
          placeholder="Search memo or counterparty"
          label="Search"
          className="min-w-[180px] flex-1 sm:max-w-[320px]"
        />
        <Button
          variant="outline"
          size="sm"
          onClick={() => set("category", reviewing ? "" : "uncategorized")}
          aria-pressed={reviewing}
          className="aria-pressed:bg-accent aria-pressed:border-input"
        >
          <Inbox />
          Uncategorized
          <Chip tone={ledger.uncategorizedCount > 0 ? "warning" : "neutral"} className="tabular h-4 px-1 text-[10px]">
            {ledger.uncategorizedCount}
          </Chip>
        </Button>
        <Tabs
          value={filters.direction || "all"}
          onValueChange={(v) => set("direction", v === "all" ? "" : (v as Direction))}
        >
          <TabsList aria-label="Direction">
            <TabsTrigger value="all">All</TabsTrigger>
            <TabsTrigger value="in">In</TabsTrigger>
            <TabsTrigger value="out">Out</TabsTrigger>
            <TabsTrigger value="transfer">Transfers</TabsTrigger>
          </TabsList>
        </Tabs>
      </FilterRow>
      <FilterRow>
        <NativeSelect value={filters.account} onChange={(e) => set("account", e.target.value)} aria-label="Account">
          <option value="">All accounts</option>
          {ledger.accounts.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name} ({a.currency})
            </option>
          ))}
        </NativeSelect>
        <NativeSelect value={filters.category} onChange={(e) => set("category", e.target.value)} aria-label="Category">
          <option value="">All categories</option>
          <option value="uncategorized">Uncategorized</option>
          {(["income", "expense"] as const).map((kind) => (
            <optgroup key={kind} label={kind === "income" ? "Income" : "Expenses"}>
              {ledger.categories
                .filter((c) => c.kind === kind)
                .map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
            </optgroup>
          ))}
        </NativeSelect>
        <NativeSelect
          value={filters.counterparty}
          onChange={(e) => set("counterparty", e.target.value)}
          aria-label="Counterparty"
        >
          <option value="">All counterparties</option>
          {(["client", "vendor"] as const).map((kind) => (
            <optgroup key={kind} label={kind === "client" ? "Clients" : "Vendors"}>
              {ledger.counterparties
                .filter((c) => c.kind === kind)
                .map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
            </optgroup>
          ))}
        </NativeSelect>
        <NativeSelect
          value={filters.reconciled}
          onChange={(e) => set("reconciled", e.target.value as FilterState["reconciled"])}
          aria-label="Reconciled"
        >
          <option value="">Reconciled or not</option>
          <option value="no">Unreconciled</option>
          <option value="yes">Reconciled</option>
        </NativeSelect>
        <div className="flex items-center gap-1.5">
          <Input
            type="date"
            value={filters.from}
            onChange={(e) => set("from", e.target.value)}
            aria-label="From"
            className="w-[140px]"
          />
          <span className="text-subtle-foreground text-xs">to</span>
          <Input
            type="date"
            value={filters.to}
            onChange={(e) => set("to", e.target.value)}
            aria-label="To"
            className="w-[140px]"
          />
        </div>
        {active && (
          <Button variant="ghost" size="sm" className="text-muted-foreground" onClick={() => onChange(EMPTY_FILTERS)}>
            <X />
            Clear
          </Button>
        )}
      </FilterRow>
    </div>
  );
}
