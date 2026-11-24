export interface CountedTab {
  value: string;
  count?: number;
}

/**
 * The tabs of a list filter worth offering: "all", the one selected, and each
 * that narrows the list (some rows, not every row). None when nothing would
 * narrow it, so a filter that cannot split the list is not shown. Unknown
 * counts (still loading) keep every tab.
 */
export function usefulFilterTabs<T extends CountedTab>(
  tabs: T[],
  active: string,
  all = "all"
): T[] {
  if (tabs.some((tab) => tab.count == null)) return tabs;
  const total = tabs.find((tab) => tab.value === all)?.count;
  const narrows = (tab: T) =>
    tab.value !== all &&
    (tab.count ?? 0) > 0 &&
    (total == null || (tab.count ?? 0) < total);
  const kept = tabs.filter(
    (tab) => tab.value === all || tab.value === active || narrows(tab)
  );
  return kept.some(narrows) || active !== all ? kept : [];
}
