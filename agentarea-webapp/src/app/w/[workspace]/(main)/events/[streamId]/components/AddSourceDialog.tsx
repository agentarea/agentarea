"use client";

import { useState, useTransition } from "react";
import { useTranslations } from "next-intl";
import {
  Braces,
  KeyRound,
  Link2,
  ListChecks,
  Loader2,
  Plus,
  Settings2,
} from "lucide-react";
import type { SourceCreated } from "@/api/client/types.gen";
import FormLabel from "@/components/FormLabel/FormLabel";
import { SecretSelect } from "@/components/SecretSelect";
import SourceTypeMark from "@/components/SourceTypeMark";
import {
  OneTimeSecretField,
  SuccessModalContent,
  SuccessModalDetail,
} from "@/components/SuccessModal";
import {
  BlueprintDialogContent,
  BlueprintFields,
} from "@/components/ui/blueprint-sheet";
import { Button } from "@/components/ui/button";
import { CopyableText } from "@/components/ui/copyable-text";
import { Dialog, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAttachableResources } from "@/hooks/use-attachable-resources";
import { sourceTypeBySlug, type SourceType } from "@/lib/sourceTypes";
import { createStreamSourceAction } from "../actions";
import {
  missingSourceFields,
  sourceKinds,
  takesEventTemplates,
  TEMPLATE_FIELDS,
  toSourceRequest,
  type SourceFormValues,
  type SourceKind,
} from "../sourceRequest";

const EMPTY: SourceFormValues = { secrets: {}, settings: {}, templates: {} };

/**
 * Add a source to a stream: pick its type from the catalog, point each
 * credential at a workspace secret, then — in the same dialog — the URL to give
 * the sender and any secret issued for it, shown once.
 */
export default function AddSourceDialog({
  streamId,
  types,
}: {
  streamId: string;
  types: SourceType[];
}) {
  const t = useTranslations("EventsPage.sources");
  const [open, setOpen] = useState(false);
  const [typeId, setTypeId] = useState("");
  const [values, setValues] = useState<SourceFormValues>(EMPTY);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<SourceCreated | null>(null);
  const [pending, startTransition] = useTransition();
  const resources = useAttachableResources({ withSecrets: true });

  const type = sourceTypeBySlug(types, typeId);
  const kinds = type ? sourceKinds(type) : [];
  const missing = type ? missingSourceFields(type, values) : [];

  const reset = () => {
    setTypeId("");
    setValues(EMPTY);
    setError(null);
    setCreated(null);
  };

  const onOpenChange = (next: boolean) => {
    if (pending) return;
    if (!next) reset();
    setOpen(next);
  };

  const submit = () => {
    if (!type) return;
    setError(null);
    startTransition(async () => {
      const result = await createStreamSourceAction(
        streamId,
        toSourceRequest(type, values)
      );
      if (result.error !== null) {
        setError(result.error);
        return;
      }
      setCreated(result.source);
    });
  };

  const setField = (
    group: "secrets" | "settings" | "templates",
    key: string,
    value: string
  ) =>
    setValues((previous) => ({
      ...previous,
      [group]: { ...previous[group], [key]: value },
    }));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button className="shrink-0" size="xs">
          <Plus />
          {t("add")}
        </Button>
      </DialogTrigger>
      {created ? (
        <SuccessModalContent
          title={t("created.title")}
          description={t("created.description")}
          doneLabel={t("created.done")}
          onDone={() => onOpenChange(false)}
        >
          {created.webhook_url && (
            <div className="min-w-0 space-y-2">
              <FormLabel icon={Link2}>{t("created.urlLabel")}</FormLabel>
              <CopyableText text={created.webhook_url} />
            </div>
          )}
          {Object.entries(created.issued ?? {}).map(([key, value]) => (
            <OneTimeSecretField
              key={key}
              label={
                type?.credentials.find((field) => field.key === key)?.label ??
                key
              }
              icon={KeyRound}
              value={value}
              warning={t("created.secretWarning")}
            />
          ))}
          {type?.verification_header && (
            <SuccessModalDetail label={t("signedWith")}>
              <code className="font-mono text-[12px] text-foreground">
                {type.verification_header}
              </code>
            </SuccessModalDetail>
          )}
        </SuccessModalContent>
      ) : (
        <BlueprintDialogContent
          title={t("dialog.title")}
          description={t("dialog.description")}
          note={t("dialog.note")}
          actions={
            <Button
              size="sm"
              onClick={submit}
              disabled={pending || !type || missing.length > 0}
            >
              {pending && <Loader2 className="animate-spin" />}
              {t("dialog.submit")}
            </Button>
          }
        >
          <BlueprintFields>
            <div className="space-y-2">
              <FormLabel htmlFor="source-type" required>
                {t("dialog.type")}
              </FormLabel>
              <Select
                value={typeId}
                onValueChange={(value) => {
                  setTypeId(value);
                  setError(null);
                }}
              >
                <SelectTrigger id="source-type" aria-label={t("dialog.type")}>
                  <SelectValue placeholder={t("dialog.typePlaceholder")} />
                </SelectTrigger>
                <SelectContent>
                  {types.map((entry) => (
                    <SelectItem key={entry.slug} value={entry.slug}>
                      <span className="flex items-center gap-2">
                        <span className="flex h-4 w-4 shrink-0 items-center justify-center">
                          <SourceTypeMark type={entry} inline />
                        </span>
                        {entry.name}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {type && <p className="note">{type.description}</p>}
            </div>

            {kinds.length > 1 && (
              <div className="space-y-2">
                <FormLabel htmlFor="source-kind" required>
                  {t("dialog.kind")}
                </FormLabel>
                <Select
                  value={values.kind ?? kinds[0]}
                  onValueChange={(value) =>
                    setValues((previous) => ({
                      ...previous,
                      kind: kinds.find((kind) => kind === value),
                    }))
                  }
                >
                  <SelectTrigger id="source-kind" aria-label={t("dialog.kind")}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {kinds.map((kind: SourceKind) => (
                      <SelectItem key={kind} value={kind}>
                        {t(`dialog.kinds.${kind}`)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}

            {type?.credentials.map((field) => (
              <div key={`${type.slug}:${field.key}`} className="space-y-2">
                <FormLabel
                  htmlFor={`source-secret-${field.key}`}
                  icon={KeyRound}
                  required={field.required && !field.issued}
                  optional={!field.required || field.issued}
                >
                  {field.label}
                </FormLabel>
                <SecretSelect
                  id={`source-secret-${field.key}`}
                  secrets={resources.secrets}
                  value={values.secrets[field.key] ?? ""}
                  onChange={(secretId) =>
                    setField("secrets", field.key, secretId)
                  }
                  disabled={
                    resources.loading || resources.failed.includes("secrets")
                  }
                  required={field.required && !field.issued}
                  placeholder={
                    resources.loading
                      ? t("dialog.loadingSecrets")
                      : t("dialog.selectSecret")
                  }
                  searchPlaceholder={t("dialog.selectSecret")}
                  emptyMessage={t("dialog.noSecrets")}
                  createLabel={t("dialog.newSecret")}
                  onCreated={resources.refresh}
                />
                {field.issued ? (
                  <p className="note">{t("dialog.issuedHint")}</p>
                ) : (
                  field.placeholder && (
                    <p className="note">{field.placeholder}</p>
                  )
                )}
              </div>
            ))}
            {type && resources.failed.includes("secrets") && (
              <p role="alert" className="text-xs text-destructive">
                {t("dialog.secretsLoadFailed")}
              </p>
            )}

            {type?.config.map((field) => (
              <div key={`${type.slug}:${field.key}`} className="space-y-2">
                <FormLabel
                  htmlFor={`source-setting-${field.key}`}
                  icon={Settings2}
                  required={field.required && !field.issued}
                  optional={!field.required || field.issued}
                >
                  {field.label}
                </FormLabel>
                <Input
                  id={`source-setting-${field.key}`}
                  value={values.settings[field.key] ?? ""}
                  placeholder={field.placeholder}
                  autoComplete="off"
                  onChange={(event) =>
                    setField("settings", field.key, event.target.value)
                  }
                />
              </div>
            ))}

            {type && takesEventTemplates(type) && (
              <div className="space-y-3">
                {TEMPLATE_FIELDS.map((field) => (
                  <div key={field} className="space-y-2">
                    <FormLabel
                      htmlFor={`source-template-${field}`}
                      icon={Braces}
                      optional
                    >
                      {t(`dialog.templates.${field}`)}
                    </FormLabel>
                    <Input
                      id={`source-template-${field}`}
                      value={values.templates[field] ?? ""}
                      placeholder={t(`dialog.templates.${field}Placeholder`)}
                      autoComplete="off"
                      className="font-mono"
                      onChange={(event) =>
                        setField("templates", field, event.target.value)
                      }
                    />
                  </div>
                ))}
                <p className="note">{t("dialog.templates.hint")}</p>
                <p className="note">{t("dialog.templates.noKeyHint")}</p>
              </div>
            )}

            {type && type.events.length > 0 && (
              <div className="space-y-2">
                <FormLabel icon={ListChecks}>{t("dialog.events")}</FormLabel>
                <p className="note">{t("dialog.eventsHint")}</p>
                <div className="flex flex-wrap gap-1.5">
                  {type.events.map((event) => (
                    <code
                      key={event}
                      className="rounded-md bg-muted px-2 py-0.5 font-mono text-xs text-muted-foreground"
                    >
                      {event}
                    </code>
                  ))}
                </div>
              </div>
            )}

            {error && (
              <p className="form-error" role="alert">
                {error}
              </p>
            )}
          </BlueprintFields>
        </BlueprintDialogContent>
      )}
    </Dialog>
  );
}
