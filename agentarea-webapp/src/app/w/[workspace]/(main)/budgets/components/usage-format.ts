const UNITS = ["B", "KiB", "MiB", "GiB", "TiB"] as const;

/** A size in GiB as a number in the largest unit that keeps it at 1 or more. */
export function splitBytes(gib: number): {
  value: number;
  unit: (typeof UNITS)[number];
} {
  let value = gib * 1024 ** 3;
  let i = 0;
  while (value >= 1024 && i < UNITS.length - 1) {
    value /= 1024;
    i += 1;
  }
  return { value, unit: UNITS[i] };
}
