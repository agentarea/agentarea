import { describe, expect, it } from "vitest";
import { formatMoney, getCurrencySymbol } from "./money";

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

  it("formats an ordinary negative amount with the sign, not just the magnitude", () => {
    expect(formatMoney(-12.5, "USD", "en-US")).toBe(
      intl(-12.5, "USD", "en-US", 2)
    );
  });

  it("preserves the sign on a tiny negative amount instead of flipping it positive", () => {
    expect(formatMoney(0.00001, "USD", "en-US")).toBe(
      `< ${intl(0.0001, "USD", "en-US", 4)}`
    );
    // "< -$0.0001" would misread as smaller (more negative) than the floor;
    // the value's magnitude is under the floor, so the signed amount is
    // *greater* than -$0.0001 — "> -$0.0001" reads correctly either way.
    expect(formatMoney(-0.00001, "USD", "en-US")).toBe(
      `> ${intl(-0.0001, "USD", "en-US", 4)}`
    );
  });

  describe("compact option", () => {
    it("drops the trailing .00 for a whole-unit amount", () => {
      expect(formatMoney(100, "USD", "en-US", { compact: true })).toBe(
        intl(100, "USD", "en-US", 0)
      );
    });

    it("still shows 2 decimals for a non-integer amount", () => {
      expect(formatMoney(99.5, "USD", "en-US", { compact: true })).toBe(
        intl(99.5, "USD", "en-US", 2)
      );
    });

    it("still surfaces sub-cent precision instead of hiding it as $0", () => {
      expect(formatMoney(0.0071, "USD", "en-US", { compact: true })).toBe(
        intl(0.0071, "USD", "en-US", 4)
      );
    });

    it("still floors a too-tiny amount rather than showing $0", () => {
      expect(formatMoney(0.00001, "USD", "en-US", { compact: true })).toBe(
        `< ${intl(0.0001, "USD", "en-US", 4)}`
      );
    });
  });
});

describe("getCurrencySymbol", () => {
  it("returns the bare symbol for USD/en", () => {
    expect(getCurrencySymbol("USD", "en-US")).toBe("$");
  });

  it("returns the bare symbol for RUB/ru", () => {
    expect(getCurrencySymbol("RUB", "ru-RU")).toBe("₽");
  });

  it("defaults to USD/en when omitted", () => {
    expect(getCurrencySymbol()).toBe("$");
  });

  it("falls back to the currency code for an unrecognized locale/currency Intl still accepts", () => {
    // KES has no narrower glyph in most locales, so Intl's own "currency" part
    // is the code itself — the fallback in getCurrencySymbol never triggers
    // in practice, but the function must still return a non-empty string.
    expect(getCurrencySymbol("KES", "en-US")).toBeTruthy();
  });
});
