import { z } from "zod";
import type { ModelSpecCreate } from "@/api/client/types.gen";

const DECIMAL = /^\d+(\.\d+)?$/;

export const manualModelSpecSchema = z.object({
  model_name: z.string().trim().min(1),
  context_window: z
    .string()
    .trim()
    .regex(/^[1-9]\d*$/),
  input_per_million: z
    .string()
    .trim()
    .refine((value) => value === "" || DECIMAL.test(value)),
  output_per_million: z
    .string()
    .trim()
    .refine((value) => value === "" || DECIMAL.test(value)),
});

export type ManualModelSpec = z.input<typeof manualModelSpecSchema>;

// Moves the decimal point six places left on the string itself: a float would
// print 0.15e-6 as "1.5e-7", which the contract's decimal pattern rejects.
export function perMillionToPerToken(perMillion: string): string | null {
  const value = perMillion.trim();
  if (value === "") return null;
  const [whole, fraction = ""] = value.split(".");
  const digits = `${whole.padStart(7, "0")}${fraction}`;
  const point = digits.length - fraction.length - 6;
  const result = `${digits.slice(0, point)}.${digits.slice(point)}`
    .replace(/^0+(?=\d)/, "")
    .replace(/\.?0+$/, "");
  return result === "" ? "0" : result;
}

export function toModelSpecCreate(
  providerSpecId: string,
  form: ManualModelSpec
): ModelSpecCreate {
  const modelName = form.model_name.trim();
  return {
    provider_spec_id: providerSpecId,
    model_name: modelName,
    display_name: modelName,
    context_window: Number(form.context_window),
    input_cost_per_token: perMillionToPerToken(form.input_per_million),
    output_cost_per_token: perMillionToPerToken(form.output_per_million),
  };
}
