import type { Direction } from "@shared/books";
import type { Ledger } from "@shared/schema";
import { Check, X } from "lucide-react";
import { useState, type FormEvent } from "react";
import { InlineStatus, type Status } from "@kit/components/notes";
import { Button } from "@kit/ui/button";
import { Input } from "@kit/ui/input";
import { NativeSelect } from "@kit/ui/native-select";
import { TableCell, TableRow } from "@kit/ui/table";
import { CategorySelect } from "./category-select";

export type NewTransaction = {
  date: string;
  account: string;
  direction: Direction;
  amount: string;
  base_amount?: string;
  to_account?: string;
  to_amount?: string;
  counterparty?: string;
  category?: string;
  description: string;
};

/** The first row of the ledger, for typing one transaction in; it stays open for the next one. */
export function AddRow({
  ledger,
  onSubmit,
  onClose,
}: {
  ledger: Ledger;
  onSubmit: (input: NewTransaction) => Promise<string | null>;
  onClose: () => void;
}) {
  const accounts = ledger.accounts.filter((a) => !a.archived);
  const [form, setForm] = useState({
    date: ledger.today,
    account: accounts[0]?.id ?? "",
    direction: "out" as Direction,
    amount: "",
    baseAmount: "",
    toAccount: "",
    toAmount: "",
    counterparty: "",
    category: "",
    description: "",
  });
  const [status, setStatus] = useState<Status>(null);
  const set = (patch: Partial<typeof form>) => setForm((current) => ({ ...current, ...patch }));

  const account = accounts.find((a) => a.id === form.account);
  const to = accounts.find((a) => a.id === form.toAccount);
  const transfer = form.direction === "transfer";
  const needsBase =
    account && account.currency !== ledger.baseCurrency && !(transfer && to?.currency === ledger.baseCurrency);
  const needsToAmount = transfer && account && to && to.currency !== account.currency;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setStatus({ kind: "busy", text: "Saving…" });
    const error = await onSubmit({
      date: form.date,
      account: form.account,
      direction: form.direction,
      amount: form.amount,
      ...(needsBase && form.baseAmount ? { base_amount: form.baseAmount } : {}),
      ...(transfer ? { to_account: form.toAccount } : {}),
      ...(needsToAmount && form.toAmount ? { to_amount: form.toAmount } : {}),
      ...(!transfer && form.counterparty ? { counterparty: form.counterparty } : {}),
      ...(!transfer && form.category ? { category: form.category } : {}),
      description: form.description,
    });
    if (error) {
      setStatus({ kind: "error", text: error });
      return;
    }
    setStatus({ kind: "ok", text: "Added" });
    set({ amount: "", baseAmount: "", toAmount: "", description: "", counterparty: "", category: "" });
  };

  const formId = "add-transaction";
  return (
    <>
      <TableRow className="bg-info-surface/60 hover:bg-info-surface/60 align-top">
        <TableCell className="pl-3">
          <form id={formId} onSubmit={submit} />
        </TableCell>
        <TableCell className="py-1.5">
          <Input
            form={formId}
            type="date"
            value={form.date}
            onChange={(e) => set({ date: e.target.value })}
            aria-label="Date"
            className="h-7 w-[132px] text-xs"
            required
          />
        </TableCell>
        <TableCell className="hidden py-1.5 md:table-cell">
          <NativeSelect
            form={formId}
            size="sm"
            value={form.account}
            onChange={(e) => set({ account: e.target.value })}
            aria-label="Account"
            className="w-[150px]"
          >
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} ({a.currency})
              </option>
            ))}
          </NativeSelect>
        </TableCell>
        <TableCell className="hidden py-1.5 md:table-cell">
          {transfer ? (
            <NativeSelect
              form={formId}
              size="sm"
              value={form.toAccount}
              onChange={(e) => set({ toAccount: e.target.value })}
              aria-label="To account"
              className="w-[160px]"
              required
            >
              <option value="">To account…</option>
              {accounts
                .filter((a) => a.id !== form.account)
                .map((a) => (
                  <option key={a.id} value={a.id}>
                    → {a.name} ({a.currency})
                  </option>
                ))}
            </NativeSelect>
          ) : (
            <NativeSelect
              form={formId}
              size="sm"
              value={form.counterparty}
              onChange={(e) => set({ counterparty: e.target.value })}
              aria-label="Counterparty"
              className="w-[160px]"
            >
              <option value="">No counterparty</option>
              {ledger.counterparties.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </NativeSelect>
          )}
        </TableCell>
        <TableCell className="py-1.5">
          <div className="mb-1 flex flex-col gap-1 md:hidden">
            <NativeSelect
              form={formId}
              size="sm"
              value={form.account}
              onChange={(e) => set({ account: e.target.value })}
              aria-label="Account"
              className="w-full"
            >
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} ({a.currency})
                </option>
              ))}
            </NativeSelect>
            {transfer ? (
              <NativeSelect
                form={formId}
                size="sm"
                value={form.toAccount}
                onChange={(e) => set({ toAccount: e.target.value })}
                aria-label="To account"
                className="w-full"
              >
                <option value="">To account…</option>
                {accounts
                  .filter((a) => a.id !== form.account)
                  .map((a) => (
                    <option key={a.id} value={a.id}>
                      → {a.name} ({a.currency})
                    </option>
                  ))}
              </NativeSelect>
            ) : (
              <NativeSelect
                form={formId}
                size="sm"
                value={form.counterparty}
                onChange={(e) => set({ counterparty: e.target.value })}
                aria-label="Counterparty"
                className="w-full"
              >
                <option value="">No counterparty</option>
                {ledger.counterparties.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </NativeSelect>
            )}
          </div>
          <Input
            form={formId}
            value={form.description}
            onChange={(e) => set({ description: e.target.value })}
            placeholder="What was it for"
            aria-label="Description"
            className="h-7 min-w-[180px] text-xs"
            required
          />
        </TableCell>
        <TableCell className="py-1.5">
          {transfer ? (
            <span className="text-subtle-foreground text-xs">No category for transfers</span>
          ) : (
            <CategorySelect
              ledger={ledger}
              value={form.category}
              onChange={(category) => set({ category })}
              placeholder="Review later"
              aria-label="Category"
              className="w-[160px]"
            />
          )}
        </TableCell>
        <TableCell className="py-1.5">
          <div className="flex flex-col items-end gap-1">
            <div className="flex items-center gap-1">
              <NativeSelect
                form={formId}
                size="sm"
                value={form.direction}
                onChange={(e) => set({ direction: e.target.value as Direction })}
                aria-label="Direction"
                className="w-[64px]"
              >
                <option value="out">Out</option>
                <option value="in">In</option>
                <option value="transfer">⇄</option>
              </NativeSelect>
              <Input
                form={formId}
                inputMode="decimal"
                value={form.amount}
                onChange={(e) => set({ amount: e.target.value })}
                placeholder={`0,00 ${account?.currency ?? ""}`}
                aria-label="Amount"
                className="tabular h-7 w-[112px] text-right text-xs"
                required
              />
            </div>
            {needsBase && (
              <Input
                form={formId}
                inputMode="decimal"
                value={form.baseAmount}
                onChange={(e) => set({ baseAmount: e.target.value })}
                placeholder={`in ${ledger.baseCurrency}`}
                aria-label={`Amount in ${ledger.baseCurrency}`}
                className="tabular h-7 w-[112px] text-right text-xs"
                required
              />
            )}
            {needsToAmount && (
              <Input
                form={formId}
                inputMode="decimal"
                value={form.toAmount}
                onChange={(e) => set({ toAmount: e.target.value })}
                placeholder={`received, ${to?.currency}`}
                aria-label={`Received in ${to?.currency}`}
                className="tabular h-7 w-[112px] text-right text-xs"
                required
              />
            )}
          </div>
        </TableCell>
        <TableCell className="py-1.5 pr-3">
          <div className="flex items-center justify-end gap-1">
            <Button
              form={formId}
              type="submit"
              size="xs"
              disabled={status?.kind === "busy"}
              aria-label="Save transaction"
            >
              <Check />
            </Button>
            <Button type="button" variant="ghost" size="xs" onClick={onClose} aria-label="Close">
              <X />
            </Button>
          </div>
        </TableCell>
      </TableRow>
      {status && (
        <TableRow className="bg-info-surface/60 hover:bg-info-surface/60">
          <TableCell colSpan={8} className="py-1 pl-12">
            <InlineStatus status={status} />
          </TableCell>
        </TableRow>
      )}
    </>
  );
}
