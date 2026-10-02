import type {
  SetupField as ApiSetupField,
  SetupFieldType,
} from "@/api/client/types.gen";

export type SetupFieldView = Omit<
  ApiSetupField,
  "default" | "required" | "type"
> & {
  default?: string | number | boolean | null;
  required: boolean;
  type: SetupFieldType;
};
