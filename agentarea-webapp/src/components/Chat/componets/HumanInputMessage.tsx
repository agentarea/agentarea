"use client";

import React, { useId, useMemo, useState } from "react";
import { Check, KeyRound, Lock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type {
  HumanInputField,
  HumanInputRequestData,
  HumanInputSecretValue,
} from "../types";
import BaseMessage from "./BaseMessage";
import MessageWrapper from "./MessageWrapper";

interface Props {
  data: HumanInputRequestData;
}

type FieldValue = string | number | boolean | string[];

function initialValue(field: HumanInputField): FieldValue {
  switch (field.type) {
    case "boolean":
      return false;
    case "multiselect":
      return [];
    default:
      return "";
  }
}

const HumanInputMessage: React.FC<Props> = ({ data }) => {
  const formId = useId();
  const fields = useMemo(() => data.questions ?? [], [data.questions]);
  const hasSecret = fields.some((f) => f.type === "secret");

  const [values, setValues] = useState<Record<string, FieldValue>>(() =>
    Object.fromEntries(fields.map((f) => [f.id, initialValue(f)]))
  );
  const [submitted, setSubmitted] = useState(false);

  const setValue = (id: string, v: FieldValue) =>
    setValues((prev) => ({ ...prev, [id]: v }));

  const isResolved = data.resolved || submitted;

  // A required field is satisfied when it holds a non-empty value.
  const canSubmit = useMemo(() => {
    return fields.every((f) => {
      if (f.required === false) return true;
      const v = values[f.id];
      if (f.type === "boolean") return true; // false is a valid answer
      if (f.type === "multiselect") return Array.isArray(v) && v.length > 0;
      return v != null && String(v).trim().length > 0;
    });
  }, [fields, values]);

  const handleSubmit = () => {
    if (!canSubmit) return;
    const answers: Record<string, unknown> = {};
    const secrets: Record<string, HumanInputSecretValue> = {};

    for (const f of fields) {
      const v = values[f.id];
      if (f.type === "secret") {
        const str = v == null ? "" : String(v);
        if (str.length > 0) {
          secrets[f.id] = f.secret_name
            ? { value: str, secret_name: f.secret_name }
            : { value: str };
        }
      } else {
        answers[f.id] = v;
      }
    }

    setSubmitted(true);
    data._onSubmit?.(data.input_request_id, answers, secrets);
  };

  const renderField = (field: HumanInputField) => {
    const value = values[field.id];
    const inputId = `${formId}-${field.id}`;
    const label = (htmlFor?: string) => (
      <Label
        htmlFor={htmlFor}
        className="flex items-center gap-1.5 text-xs font-medium text-foreground"
      >
        {field.type === "secret" && <Lock className="h-3 w-3 text-amber-500" />}
        {field.question}
      </Label>
    );

    switch (field.type) {
      case "secret":
        return (
          <div key={field.id} className="flex flex-col gap-1">
            {label(inputId)}
            <Input
              id={inputId}
              type="password"
              autoComplete="off"
              placeholder="••••••••"
              value={value as string}
              onChange={(e) => setValue(field.id, e.target.value)}
            />
            <span className="text-[11px] text-muted-foreground">
              Stored securely — the agent receives a reference, never the value.
            </span>
          </div>
        );

      case "textarea":
        return (
          <div key={field.id} className="flex flex-col gap-1">
            {label(inputId)}
            <Textarea
              id={inputId}
              value={value as string}
              onChange={(e) => setValue(field.id, e.target.value)}
              className="min-h-[70px] text-sm"
            />
          </div>
        );

      case "number":
        return (
          <div key={field.id} className="flex flex-col gap-1">
            {label(inputId)}
            <Input
              id={inputId}
              type="number"
              value={value as string}
              onChange={(e) => setValue(field.id, e.target.value)}
            />
          </div>
        );

      case "boolean":
        return (
          <label
            key={field.id}
            className="flex items-center gap-2 text-sm text-foreground"
          >
            <input
              type="checkbox"
              checked={value as boolean}
              onChange={(e) => setValue(field.id, e.target.checked)}
              className="rounded"
            />
            {field.question}
          </label>
        );

      case "select":
        return (
          <div key={field.id} className="flex flex-col gap-1">
            {label()}
            <div className="flex flex-col gap-1">
              {(field.options ?? []).map((opt) => (
                <label
                  key={opt}
                  className="flex items-center gap-2 text-sm text-foreground"
                >
                  <input
                    type="radio"
                    name={field.id}
                    checked={value === opt}
                    onChange={() => setValue(field.id, opt)}
                  />
                  {opt}
                </label>
              ))}
            </div>
          </div>
        );

      case "multiselect":
        return (
          <div key={field.id} className="flex flex-col gap-1">
            {label()}
            <div className="flex flex-col gap-1">
              {(field.options ?? []).map((opt) => {
                const arr = (value as string[]) ?? [];
                const checked = arr.includes(opt);
                return (
                  <label
                    key={opt}
                    className="flex items-center gap-2 text-sm text-foreground"
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={(e) =>
                        setValue(
                          field.id,
                          e.target.checked
                            ? [...arr, opt]
                            : arr.filter((o) => o !== opt)
                        )
                      }
                    />
                    {opt}
                  </label>
                );
              })}
            </div>
          </div>
        );

      default: // text
        return (
          <div key={field.id} className="flex flex-col gap-1">
            {label(inputId)}
            <Input
              id={inputId}
              type="text"
              value={value as string}
              onChange={(e) => setValue(field.id, e.target.value)}
            />
          </div>
        );
    }
  };

  if (isResolved) {
    return (
      <MessageWrapper type="tool-result" icon={<Check className="text-muted-foreground" />}>
        <details className="group min-w-0 flex-1 text-[13px] leading-5">
          <summary className="flex cursor-pointer list-none items-center gap-2 rounded-md px-1 py-0.5 text-foreground/80 outline-none hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
            <span className="font-medium">Information provided</span>
            <span className="min-w-0 truncate text-muted-foreground">
              {data.question || "Additional information"}
            </span>
          </summary>
          <div className="space-y-1 pb-1 pl-3 pt-1 text-muted-foreground">
            <p>Response submitted. The task has resumed.</p>
            {fields.length > 0 && (
              <ul className="list-disc space-y-0.5 pl-4">
                {fields.map((field) => (
                  <li key={field.id}>{field.question}</li>
                ))}
              </ul>
            )}
          </div>
        </details>
      </MessageWrapper>
    );
  }

  return (
    <MessageWrapper
      type="tool-call"
      icon={
        hasSecret ? (
          <KeyRound className="text-amber-500" />
        ) : (
          <Check className="text-zinc-700 dark:text-zinc-200" />
        )
      }
    >
      <BaseMessage
        headerLeft={
          <div className="flex items-center gap-1.5">
            <span className="font-medium text-foreground">
              {data.question || "Additional information needed"}
            </span>
          </div>
        }
        headerRight={
          <span className="animate-pulse text-amber-600">Input required</span>
        }
        collapsed={false}
      >
        <div className="space-y-3">
          <div className="space-y-3">{fields.map(renderField)}</div>
          <Button size="sm" onClick={handleSubmit} disabled={!canSubmit}>
            Submit
          </Button>
        </div>
      </BaseMessage>
    </MessageWrapper>
  );
};

export default HumanInputMessage;
