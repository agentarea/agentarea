const digitsCache = new Map<string, number>();

/** Decimal places of a currency's minor unit: 2 for RUB/USD/EUR, 0 for JPY. */
export function minorDigits(currency: string): number {
  let digits = digitsCache.get(currency);
  if (digits === undefined) {
    digits = new Intl.NumberFormat("en-US", { style: "currency", currency }).resolvedOptions().maximumFractionDigits ?? 2;
    digitsCache.set(currency, digits);
  }
  return digits;
}

/**
 * Parses a major-unit amount ("1250.5", "1 250,50", 1250.5) into integer minor
 * units without going through float arithmetic.
 */
export function toMinor(input: number | string, currency: string): number {
  const digits = minorDigits(currency);
  let text = typeof input === "number" ? numberToPlain(input) : input.trim();
  text = text.replace(/[\s  ']/g, "");
  // With both separators the last one is the decimal point; a lone comma is one too.
  if (text.includes(",") && text.includes(".")) {
    text = text.lastIndexOf(",") > text.lastIndexOf(".") ? text.replace(/\./g, "").replace(",", ".") : text.replace(/,/g, "");
  } else if (/^-?\d+,\d+$/.test(text)) {
    text = text.replace(",", ".");
  }
  const match = /^(-)?(\d+)(?:\.(\d+))?$/.exec(text);
  if (!match) throw new Error(`"${String(input)}" is not an amount`);
  const [, minus, whole, fraction = ""] = match;
  if (fraction.length > digits) {
    throw new Error(`${String(input)} has more than ${digits} decimal places for ${currency}`);
  }
  const minor = Number(whole) * 10 ** digits + Number(fraction.padEnd(digits, "0") || "0");
  if (!Number.isSafeInteger(minor)) throw new Error(`${String(input)} is too large`);
  return minus ? -minor : minor;
}

function numberToPlain(value: number): string {
  if (!Number.isFinite(value)) throw new Error(`${value} is not an amount`);
  // Shortest round-trip form, e.g. 0.1 + 0.2 stays "0.30000000000000004" and is rejected.
  return Number.isInteger(value) ? value.toFixed(0) : String(value);
}

export function toMajor(minor: number, currency: string): number {
  return minor / 10 ** minorDigits(currency);
}

const formatters = new Map<string, Intl.NumberFormat>();

/** `compact`: "1,2 млн ₽"; `whole`: no minor digits, for headline figures. */
export function formatMoney(
  minor: number,
  currency: string,
  locale = "ru-RU",
  options: { compact?: boolean; whole?: boolean } = {},
) {
  const key = `${locale}|${currency}|${options.compact ? "c" : ""}${options.whole ? "w" : ""}`;
  let formatter = formatters.get(key);
  if (!formatter) {
    formatter = new Intl.NumberFormat(locale, {
      style: "currency",
      currency,
      ...(options.compact ? { notation: "compact", maximumFractionDigits: 1 } : {}),
      ...(options.whole ? { minimumFractionDigits: 0, maximumFractionDigits: 0 } : {}),
    });
    formatters.set(key, formatter);
  }
  return formatter.format(toMajor(minor, currency));
}

/** Rounds half away from zero; used wherever a share of a minor amount is taken. */
export function roundMinor(value: number): number {
  return Math.sign(value) * Math.round(Math.abs(value));
}
