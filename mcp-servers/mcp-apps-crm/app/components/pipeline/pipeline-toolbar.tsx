import { PersonAvatar } from "@kit/components/person-avatar";
import {
  FilterRow,
  LayoutTabs,
  RefreshButton,
  SearchField,
  ViewHeader,
  type LayoutMode,
} from "@kit/components/view-header";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from "@kit/ui/select";
import type { PipelineSnapshot } from "@shared/schema";
import { Handshake } from "lucide-react";
import type { ReactNode } from "react";
import { formatMoneyShort } from "@/lib/format";

export const ALL_OWNERS = "all";

export function PipelineToolbar({
  snapshot,
  shown,
  ownerId,
  onOwnerChange,
  query,
  onQueryChange,
  view,
  onViewChange,
  loading,
  onRefresh,
  status,
}: {
  snapshot: PipelineSnapshot | null;
  shown: number;
  ownerId: string;
  onOwnerChange: (ownerId: string) => void;
  query: string;
  onQueryChange: (query: string) => void;
  view: LayoutMode;
  onViewChange: (view: LayoutMode) => void;
  loading: boolean;
  onRefresh: () => void;
  status: ReactNode;
}) {
  const owners = snapshot?.owners ?? [];
  const total = snapshot?.deals.length ?? 0;
  const rotting = snapshot?.deals.filter((d) => d.rotting).length ?? 0;

  return (
    <header className="flex flex-col gap-3">
      <ViewHeader
        icon={Handshake}
        title={snapshot?.pipeline.name ?? "Sales pipeline"}
        subtitle={
          snapshot ? (
            <>
              {snapshot.account} · {shown === total ? `${total} deals` : `${shown} of ${total} deals`} ·{" "}
              {formatMoneyShort(snapshot.kpis.openValue, snapshot.baseCurrency)} open
              {rotting > 0 && <span className="text-danger"> · {rotting} rotting</span>}
            </>
          ) : (
            "Connecting to the CRM server…"
          )
        }
        actions={
          <>
            <LayoutTabs value={view} onChange={onViewChange} />
            <RefreshButton busy={loading} onClick={onRefresh} label="Reload from the CRM server" />
          </>
        }
      />
      <FilterRow>
        <Select value={ownerId} onValueChange={onOwnerChange}>
          <SelectTrigger size="sm" className="min-w-[150px] flex-1 sm:flex-none" aria-label="Owner">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_OWNERS}>All owners</SelectItem>
            {(["human", "agent"] as const).map((kind) => (
              <SelectGroup key={kind}>
                <SelectSeparator />
                <SelectLabel>{kind === "human" ? "People" : "Agents"}</SelectLabel>
                {owners
                  .filter((o) => o.kind === kind)
                  .map((o) => (
                    <SelectItem key={o.id} value={o.id}>
                      <PersonAvatar person={o} className="size-4" />
                      {o.name}
                    </SelectItem>
                  ))}
              </SelectGroup>
            ))}
          </SelectContent>
        </Select>
        <SearchField
          value={query}
          onChange={onQueryChange}
          placeholder="Filter by deal, company or contact"
          label="Filter deals"
        />
        {status}
      </FilterRow>
    </header>
  );
}
