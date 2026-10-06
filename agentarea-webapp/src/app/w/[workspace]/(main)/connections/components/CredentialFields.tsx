"use client";

import type { ChangeEvent, FocusEvent, RefCallback } from "react";
import { Key, Lock } from "lucide-react";
import { useTranslations } from "next-intl";
import FormLabel from "@/components/FormLabel/FormLabel";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { CredentialFieldSpec } from "../credential-fields";

type FieldElement = HTMLInputElement | HTMLSelectElement;

/** What binds one input to its form: `register(...)` or a value/onChange pair. */
export type CredentialFieldBinding = {
  name?: string;
  value?: string;
  ref?: RefCallback<FieldElement>;
  onChange: (event: ChangeEvent<FieldElement>) => void;
  onBlur?: (event: FocusEvent<FieldElement>) => void;
};

/**
 * The credential inputs of a connection — headers or environment variables,
 * secret ones masked. Pass `missingSecretFields(...)` as `fields` to ask only
 * for what the connection still lacks.
 */
export function CredentialFields({
  fields,
  bind,
  idPrefix = "field",
  disabled,
}: {
  fields: CredentialFieldSpec[];
  /** `index` is the field's position, a safe form path for any name. */
  bind: (name: string, index: number) => CredentialFieldBinding;
  idPrefix?: string;
  disabled?: boolean;
}) {
  return (
    <div className="space-y-4">
      {fields.map((field, index) => {
        const id = `${idPrefix}-${field.name}`;
        return (
          <div key={field.name} className="flex flex-col gap-2">
            <FormLabel
              htmlFor={id}
              icon={field.isSecret ? Key : undefined}
              required={field.isRequired !== false}
            >
              {field.name}
            </FormLabel>
            {field.description && (
              <p className="text-xs text-muted-foreground">
                {field.description}
              </p>
            )}
            {field.choices && field.choices.length > 0 ? (
              <select
                id={id}
                disabled={disabled}
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm"
                {...bind(field.name, index)}
              >
                <option value="">Select...</option>
                {field.choices.map((choice) => (
                  <option key={choice} value={choice}>
                    {choice}
                  </option>
                ))}
              </select>
            ) : (
              <Input
                id={id}
                type={field.isSecret ? "password" : "text"}
                placeholder={field.placeholder || ""}
                disabled={disabled}
                {...bind(field.name, index)}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

/** Where the values typed above end up, said once under every credential form. */
export function CredentialEncryptionNote({ className }: { className?: string }) {
  const t = useTranslations("MCPServersPage.createInstance.connect");
  return (
    <div
      className={cn(
        "flex items-center gap-2 text-xs text-muted-foreground",
        className
      )}
    >
      <Lock className="h-3.5 w-3.5" />
      {t("encryptionNote")}
    </div>
  );
}
