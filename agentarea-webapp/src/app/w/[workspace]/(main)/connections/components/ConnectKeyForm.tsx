"use client";

import { useTranslations } from "next-intl";
import { useForm, useWatch } from "react-hook-form";
import { FocusStep } from "@/components/FocusCard";
import { Button } from "@/components/ui/button";
import type { CredentialFieldSpec } from "../credential-fields";
import { CredentialFields } from "./CredentialFields";

/**
 * The keys a connection still needs, asked for in one step and saved together:
 * an MCP instance's missing key, or a catalog API's keys before it exists.
 */
export function ConnectKeyForm({
  fields,
  title,
  detail,
  pending,
  onSave,
}: {
  fields: CredentialFieldSpec[];
  title: string;
  detail: string;
  pending: boolean;
  /** The typed values keyed by field name. */
  onSave: (values: Record<string, string>) => void;
}) {
  const t = useTranslations("MCPServersPage.connectLink");
  // Keyed by position: a header name like "X-Api.Key" is not a form path.
  const { register, handleSubmit, control } = useForm<{ fields: string[] }>({
    defaultValues: { fields: fields.map(() => "") },
  });
  const values = useWatch({ control, name: "fields" });
  const complete = fields.every((_, index) => values?.[index]?.trim());

  return (
    <form
      onSubmit={handleSubmit((data) =>
        onSave(
          Object.fromEntries(
            fields.map((field, index) => [field.name, data.fields[index] ?? ""])
          )
        )
      )}
      className="space-y-4"
    >
      <FocusStep kind="attention" title={title} detail={detail} />
      <CredentialFields
        idPrefix="connect"
        fields={fields}
        bind={(_, index) => register(`fields.${index}`)}
      />
      <Button
        type="submit"
        size="lg"
        className="w-full"
        isLoading={pending}
        disabled={pending || !complete}
      >
        {t("saveAndConnect")}
      </Button>
    </form>
  );
}
