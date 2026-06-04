"use client";

import React from "react";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import FormLabel from "@/components/FormLabel/FormLabel";
import { cn } from "@/lib/utils";
import type { SetupField } from "@/app/(main)/bundles/types";

export interface SetupFormProps {
  schema: SetupField[];
  values: Record<string, string | number | boolean>;
  onChange: (key: string, value: string | number | boolean) => void;
  errors?: Record<string, string>;
  disabled?: boolean;
}

export default function SetupForm({
  schema,
  values,
  onChange,
  errors,
  disabled = false,
}: SetupFormProps) {
  if (!schema || schema.length === 0) {
    return (
      <p className="note">No configuration required.</p>
    );
  }

  const getErrorText = (key: string): string | undefined => {
    return errors?.[key];
  };

  return (
    <div className="grid gap-4">
      {schema.map((field) => {
        const errorText = getErrorText(field.key);
        const value = values[field.key];

        return (
          <div key={field.key} className="grid gap-2">
            <FormLabel htmlFor={`setup_${field.key}`} required={field.required}>
              {field.label}
            </FormLabel>

            {field.type === "boolean" ? (
              <Switch
                id={`setup_${field.key}`}
                checked={Boolean(value ?? field.default ?? false)}
                onCheckedChange={(checked) => onChange(field.key, checked)}
                disabled={disabled}
              />
            ) : field.type === "select" ? (
              <Select
                value={String(value ?? field.default ?? "")}
                onValueChange={(val) => onChange(field.key, val)}
                disabled={disabled}
              >
                <SelectTrigger
                  id={`setup_${field.key}`}
                  className={cn(errorText ? "border-red-300" : "")}
                >
                  <SelectValue placeholder={`Select ${field.label}`} />
                </SelectTrigger>
                <SelectContent>
                  {(field.options ?? []).map((opt) => (
                    <SelectItem key={opt} value={opt}>
                      {opt}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : field.type === "number" ? (
              <Input
                id={`setup_${field.key}`}
                type="number"
                value={String(value ?? field.default ?? "")}
                min={field.min ?? undefined}
                max={field.max ?? undefined}
                onChange={(e) => {
                  const parsed = e.target.value === "" ? "" : Number(e.target.value);
                  onChange(field.key, parsed as number);
                }}
                disabled={disabled}
                className={cn(errorText ? "border-red-300" : "")}
              />
            ) : field.type === "secret" ? (
              <Input
                id={`setup_${field.key}`}
                type="password"
                autoComplete="off"
                value={String(value ?? "")}
                onChange={(e) => onChange(field.key, e.target.value)}
                disabled={disabled}
                className={cn(errorText ? "border-red-300" : "")}
              />
            ) : (
              <Input
                id={`setup_${field.key}`}
                type="text"
                value={String(value ?? field.default ?? "")}
                onChange={(e) => onChange(field.key, e.target.value)}
                disabled={disabled}
                className={cn(errorText ? "border-red-300" : "")}
              />
            )}

            {field.help && <p className="note">{field.help}</p>}

            {errorText && (
              <p className="form-error">{errorText}</p>
            )}
          </div>
        );
      })}
    </div>
  );
}
