// What a member sets a call of their own connection to cost (wiki ADR-0038 §2.3),
// as the form edits it and as the API stores it: a cost declaration. The server
// validates the declaration; this only maps between the two shapes.

export type CostMode =
  | "connector"
  | "free"
  | "per_call"
  | "per_unit"
  | "from_response";

export interface CostForm {
  mode: CostMode;
  amount: string;
  currency: string;
  unit: string;
  // Per unit: the argument the units are counted from, or "$.path" in the response.
  quantity: string;
  // From the response: "$.path" of the cost in the response.
  path: string;
}

export type CostDeclaration = Record<string, unknown>;

const DEFAULT_CURRENCY = "USD";

export function emptyCostForm(mode: CostMode = "connector"): CostForm {
  return {
    mode,
    amount: "",
    currency: DEFAULT_CURRENCY,
    unit: "",
    quantity: "",
    path: "",
  };
}

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function text(value: unknown): string {
  return typeof value === "string" || typeof value === "number"
    ? String(value)
    : "";
}

/** The form a stored declaration is edited in; none is the connector's own cost. */
export function costToForm(cost: CostDeclaration | null | undefined): CostForm {
  const declared = record(cost);
  if (!declared) return emptyCostForm();
  if (declared.source === "free") return emptyCostForm("free");
  if (declared.source === "reported") {
    const reported = record(declared.reported) ?? {};
    return {
      ...emptyCostForm("from_response"),
      currency: text(reported.currency) || DEFAULT_CURRENCY,
      path: text(reported.path),
    };
  }
  const rate = record(declared.rate) ?? {};
  const quantity = record(rate.quantity);
  const base = {
    ...emptyCostForm(quantity ? "per_unit" : "per_call"),
    amount: text(rate.amount),
    currency: text(rate.currency) || DEFAULT_CURRENCY,
  };
  if (!quantity) return base;
  return {
    ...base,
    unit: text(declared.unit),
    quantity: text(quantity.arg) || text(quantity.path),
  };
}

/** The declaration a form stores; null goes back to the connector's own cost. */
export function formToCost(form: CostForm): CostDeclaration | null {
  const currency = form.currency.trim().toUpperCase();
  switch (form.mode) {
    case "connector":
      return null;
    case "free":
      return { source: "free" };
    case "from_response":
      return {
        source: "reported",
        reported: { path: form.path.trim(), currency },
      };
    case "per_call":
      return {
        source: "rate",
        unit: "call",
        rate: { amount: form.amount.trim(), currency },
      };
    case "per_unit": {
      const quantity = form.quantity.trim();
      return {
        source: "rate",
        unit: form.unit.trim() || "unit",
        rate: {
          amount: form.amount.trim(),
          currency,
          quantity: quantity.startsWith("$")
            ? { path: quantity }
            : { arg: quantity },
        },
      };
    }
  }
}
