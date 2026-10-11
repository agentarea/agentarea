import { LinkList, LinkRow } from "@kit/components/list";
import { InlineStatus, toStatus, type Status } from "@kit/components/notes";
import { Section } from "@kit/components/section";
import type { AccountKind } from "@shared/books";
import { toMajor } from "@shared/money";
import type { Overview } from "@shared/schema";
import { Banknote, CreditCard, Landmark, type LucideIcon } from "lucide-react";
import { useState } from "react";
import { Area, AreaChart, YAxis } from "recharts";
import { type ChartConfig, ChartContainer } from "@/components/chart";
import { Money } from "@/components/money";
import { dayMonth } from "@/lib/format";

const ICONS: Record<AccountKind, LucideIcon> = { bank: Landmark, cash: Banknote, card: CreditCard };
const chartConfig = { balance: { label: "Cash", color: "var(--chart-cash)" } } satisfies ChartConfig;

export function AccountsCard({
  overview,
  onOpenAccount,
  className,
}: {
  overview: Overview;
  onOpenAccount: (accountId: string) => Promise<string | null>;
  className?: string;
}) {
  const [status, setStatus] = useState<Status>(null);
  const { baseCurrency: base, locale } = overview.book;
  const series = overview.cashSeries.map((p) => ({ date: p.date, balance: toMajor(p.balance, base) }));

  return (
    <Section
      className={className}
      title="Accounts"
      meta={`on ${dayMonth(overview.kpis.cashAsOf, overview.today)}`}
      actions={<InlineStatus status={status} />}
    >
      <LinkList>
        {series.length > 1 && (
          <li className="border-b px-3 pt-2.5 pb-1" aria-hidden>
            <ChartContainer config={chartConfig} className="aspect-auto h-12 w-full" aria-label="Cash over the period">
              <AreaChart data={series} margin={{ top: 2, right: 0, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="cash-fill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="var(--color-balance)" stopOpacity={0.18} />
                    <stop offset="100%" stopColor="var(--color-balance)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <YAxis hide domain={["dataMin", "dataMax"]} />
                <Area
                  dataKey="balance"
                  type="monotone"
                  stroke="var(--color-balance)"
                  strokeWidth={1.25}
                  fill="url(#cash-fill)"
                  isAnimationActive={false}
                />
              </AreaChart>
            </ChartContainer>
          </li>
        )}
        {overview.accounts.map((account) => {
          const Icon = ICONS[account.kind];
          return (
            <LinkRow
              key={account.id}
              className="h-auto py-2"
              onClick={async () => setStatus(await toStatus(onOpenAccount(account.id)))}
            >
              <Icon className="text-muted-foreground size-3.5 shrink-0" />
              <span className="min-w-0 flex-1">
                <span className="block truncate">{account.name}</span>
                <span className="text-subtle-foreground block truncate text-[11px]">
                  {[
                    account.number,
                    account.currency,
                    account.unreconciled ? `${account.unreconciled} unreconciled` : "all reconciled",
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              </span>
              <span className="text-right">
                <Money
                  minor={account.balance}
                  currency={account.currency}
                  locale={locale}
                  className="block font-medium"
                />
                {account.currency !== base && (
                  <Money
                    minor={account.balanceBase}
                    currency={base}
                    locale={locale}
                    className="text-subtle-foreground block text-[11px]"
                  />
                )}
              </span>
            </LinkRow>
          );
        })}
        <li className="bg-muted/70 flex h-9 items-center justify-between px-3 text-[13px]">
          <span className="text-muted-foreground">Total in {base}</span>
          <Money minor={overview.kpis.cash} currency={base} locale={locale} className="font-semibold" />
        </li>
      </LinkList>
    </Section>
  );
}
