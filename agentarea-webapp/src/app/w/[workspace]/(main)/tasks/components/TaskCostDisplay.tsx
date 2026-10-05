"use client";

import { createContext, useContext, type ReactNode } from "react";
import { useLocale } from "next-intl";
import { useCurrency } from "@/hooks/useCurrency";
import { formatMoney } from "@/lib/money";

const TaskCostContext = createContext<{
  currency: string | null;
  locale: string;
} | null>(null);

export function TaskCostProvider({ children }: { children: ReactNode }) {
  const locale = useLocale();
  const { currency } = useCurrency();

  return (
    <TaskCostContext.Provider value={{ currency, locale }}>
      {children}
    </TaskCostContext.Provider>
  );
}

export default function TaskCostDisplay({ amount }: { amount: number }) {
  const settings = useContext(TaskCostContext);
  if (!settings) throw new Error("TaskCostDisplay requires TaskCostProvider");

  return <span>{formatMoney(amount, settings.currency, settings.locale)}</span>;
}
