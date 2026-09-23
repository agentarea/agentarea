import type { TreeNode } from "./file-tree";

const ENTRY_SORT_KEYS = ["name", "modified", "size"] as const;

export type EntrySortKey = (typeof ENTRY_SORT_KEYS)[number];

export interface EntrySort {
  accessor: EntrySortKey;
  direction: "asc" | "desc";
}

export function isEntrySortKey(accessor: string): accessor is EntrySortKey {
  return (ENTRY_SORT_KEYS as readonly string[]).includes(accessor);
}

function sortValue(entry: TreeNode, key: EntrySortKey): number | undefined {
  if (key === "size") return entry.file?.size ?? undefined;
  if (key === "modified" && entry.file?.last_modified) {
    const time = Date.parse(entry.file.last_modified);
    return Number.isNaN(time) ? undefined : time;
  }
  return undefined;
}

/** Folders stay above files in every order, as in any file manager. A file
 * with no value for the key goes last in both directions: an unknown size is
 * neither the largest nor the smallest. */
export function sortEntries<T extends TreeNode>(
  entries: T[],
  { accessor, direction }: EntrySort
): T[] {
  const sign = direction === "asc" ? 1 : -1;
  return [...entries].sort((a, b) => {
    if (a.isFile !== b.isFile) return a.isFile ? 1 : -1;
    if (accessor !== "name") {
      const left = sortValue(a, accessor);
      const right = sortValue(b, accessor);
      if (left !== undefined && right !== undefined && left !== right) {
        return (left - right) * sign;
      }
      if ((left === undefined) !== (right === undefined)) {
        return left === undefined ? 1 : -1;
      }
      return a.name.localeCompare(b.name);
    }
    return a.name.localeCompare(b.name) * sign;
  });
}
