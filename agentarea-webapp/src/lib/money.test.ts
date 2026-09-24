import { describe, expect, it } from "vitest";
import { formatMoney } from "./money";

/** Intl output for a locale/currency pair, to compare against without
 * hardcoding locale-specific whitespace (Intl uses a narrow no-break space
 * between the amount and symbol in some locales). */
function intl(value: number, currency: string, locale: string, digits: number) {
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency,
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
}

describe("formatMoney", () => {
  it("formats whole and one-cent-and-up amounts with 2 decimals", () => {
    expect(formatMoney(12.5, "USD", "en-US")).toBe("$12.50");
    expect(formatMoney(0, "USD", "en-US")).toBe("$0.00");
    expect(formatMoney(0.5, "USD", "en-US")).toBe("$0.50");
  });

  it("keeps 4 decimals for sub-cent amounts so a task cost doesn't round away", () => {
    expect(formatMoney(0.0071, "USD", "en-US")).toBe("$0.0071");
  });

  it("renders an amount too small to show at 4 decimals as a '< floor'", () => {
    expect(formatMoney(0.00001, "USD", "en-US")).toBe(
      `< ${intl(0.0001, "USD", "en-US", 4)}`
    );
  });

  it("formats in the requested currency and locale, not just USD/en-US", () => {
    expect(formatMoney(1234.5, "RUB", "ru-RU")).toBe(
      intl(1234.5, "RUB", "ru-RU", 2)
    );
    expect(formatMoney(0.0071, "RUB", "ru-RU")).toBe(
      intl(0.0071, "RUB", "ru-RU", 4)
    );
    expect(formatMoney(0.00001, "RUB", "ru-RU")).toBe(
      `< ${intl(0.0001, "RUB", "ru-RU", 4)}`
    );
  });

  it("defaults to USD/en when currency and locale are omitted", () => {
    expect(formatMoney(3)).toBe("$3.00");
  });

  it("treats non-finite input as zero rather than throwing or printing NaN", () => {
    expect(formatMoney(NaN, "USD", "en-US")).toBe("$0.00");
  });
});
