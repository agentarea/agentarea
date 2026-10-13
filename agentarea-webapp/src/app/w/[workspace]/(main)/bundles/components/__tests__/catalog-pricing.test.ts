import { describe, expect, it } from "vitest";
import {
  formatMemory,
  formatMoney,
  formatPriceNumber,
  formatVcpu,
  monthlyFromHourly,
} from "../catalog-pricing";

// Intl separates with a narrow no-break space in ru; compare on plain spaces.
const plain = (s: string) => s.replace(/[  ]/g, " ");

describe("catalog pricing format", () => {
  it("drops the currency for a chip whose icon names it, keeps it in full", () => {
    expect(formatPriceNumber("0.04", "ru")).toBe("0,04");
    expect(plain(formatMoney("0.04", "RUB", "ru"))).toBe("0,04 ₽");
    expect(formatMoney("0.0012", "USD", "en")).toBe("$0.0012");
  });

  it("reads a reservation in vCPU and MiB below a GiB, GiB above", () => {
    expect(formatVcpu("0.100", "en")).toBe("0.1");
    expect(formatMemory("0.125", "en")).toBe("128 MiB");
    expect(formatMemory("1.5", "en")).toBe("1.5 GiB");
  });

  it("prices an always-on month at 730 hours", () => {
    expect(monthlyFromHourly("0.12")).toBeCloseTo(87.6);
    expect(plain(formatMoney(773.8, "RUB", "ru", { whole: true }))).toBe(
      "774 ₽"
    );
  });
});
