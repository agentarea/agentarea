import { useMemo, useState } from "react";
import {
  buildConnectionList,
  type ConnectionListRow,
  type ListFilter,
} from "./list-sections";

export function useConnectionListFilter<T extends ConnectionListRow>(
  rows: T[]
) {
  const [filter, setFilter] = useState<ListFilter>("all");
  const list = useMemo(() => buildConnectionList(rows, filter), [rows, filter]);
  return { filter, setFilter, ...list };
}
