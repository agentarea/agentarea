import type { Ledger } from "@shared/schema";
import { CircleCheck, X } from "lucide-react";
import { useState } from "react";
import { InlineStatus, type Status } from "@kit/components/notes";
import { Button } from "@kit/ui/button";
import { NativeSelect } from "@kit/ui/native-select";
import { CategorySelect } from "./category-select";

/** Acts on the selected rows: one category (and counterparty) for all, or reconcile them. */
export function BulkBar({
  ledger,
  count,
  status,
  onCategorize,
  onReconcile,
  onClear,
}: {
  ledger: Ledger;
  count: number;
  status: Status;
  onCategorize: (categoryId: string, counterpartyId: string | null) => void;
  onReconcile: () => void;
  onClear: () => void;
}) {
  const [category, setCategory] = useState("");
  const [counterparty, setCounterparty] = useState("");
  const busy = status?.kind === "busy";
  return (
    <div className="bg-muted/70 flex flex-wrap items-center gap-2 border-b px-3 py-1.5">
      <span className="tabular text-xs font-semibold">{count} selected</span>
      <CategorySelect
        ledger={ledger}
        value={category}
        onChange={setCategory}
        placeholder="Category…"
        aria-label="Category for selected"
        className="w-[170px]"
      />
      <NativeSelect
        size="sm"
        value={counterparty}
        onChange={(e) => setCounterparty(e.target.value)}
        aria-label="Counterparty for selected"
        className="w-[170px]"
      >
        <option value="">Keep counterparty</option>
        {ledger.counterparties.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name}
          </option>
        ))}
      </NativeSelect>
      <Button size="xs" disabled={!category || busy} onClick={() => onCategorize(category, counterparty || null)}>
        Categorize
      </Button>
      <Button size="xs" variant="outline" disabled={busy} onClick={onReconcile}>
        <CircleCheck />
        Mark reconciled
      </Button>
      <Button size="xs" variant="ghost" className="text-muted-foreground" onClick={onClear}>
        <X />
        Clear
      </Button>
      <InlineStatus status={status} />
    </div>
  );
}
