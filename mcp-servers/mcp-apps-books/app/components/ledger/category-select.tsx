import type { Ledger } from "@shared/schema";
import { NativeSelect } from "@kit/ui/native-select";

/** Income and expense categories as option groups; "" is uncategorized. */
export function CategorySelect({
  ledger,
  value,
  onChange,
  disabled,
  placeholder = "Uncategorized",
  className,
  size = "sm",
  "aria-label": label,
}: {
  ledger: Ledger;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  placeholder?: string;
  className?: string;
  size?: "sm" | "default";
  "aria-label": string;
}) {
  const visible = ledger.categories.filter((c) => !c.archived || c.id === value);
  return (
    <NativeSelect
      size={size}
      value={value}
      disabled={disabled}
      aria-label={label}
      className={className}
      onChange={(event) => onChange(event.target.value)}
    >
      <option value="">{placeholder}</option>
      {(["income", "expense"] as const).map((kind) => (
        <optgroup key={kind} label={kind === "income" ? "Income" : "Expenses"}>
          {visible
            .filter((c) => c.kind === kind)
            .map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
        </optgroup>
      ))}
    </NativeSelect>
  );
}
