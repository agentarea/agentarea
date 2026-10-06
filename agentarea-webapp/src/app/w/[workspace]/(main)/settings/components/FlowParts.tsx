"use client";

import type { UiNodeGroupEnum, UiText } from "@ory/client-fetch";
import { useComponents, useOryFlow } from "@ory/elements-react";
import { useFormContext } from "react-hook-form";
import FormError from "@/components/FormError";
import { Button, type ButtonProps } from "@/components/ui/button";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { errorsOf } from "./oryNodes";

/** A Kratos message in the UI language, with its `ory/message/<id>` test id. */
export function OryText({ message }: { message: UiText }) {
  const { Message } = useComponents();
  return <Message.Content message={message} />;
}

/**
 * What Kratos says about the whole flow: its errors, or the success line after
 * a save ("Your changes have been saved!"). A save reloads the page through
 * Kratos' `continue_with` redirect, which lands at the top, so this is where
 * the outcome has to be.
 */
export function FlowMessages() {
  const { flow } = useOryFlow();
  const messages = flow.ui.messages ?? [];
  const errors = errorsOf(messages);
  const success =
    errors.length === 0 && flow.state === "success"
      ? messages.filter((message) => message.type !== "error")
      : [];
  if (errors.length === 0 && success.length === 0) return null;

  return (
    <div className="space-y-2">
      {errors.map((message, index) => (
        <FormError key={`${message.id}-${index}`}>
          <OryText message={message} />
        </FormError>
      ))}
      {success.map((message, index) => (
        <div
          key={`${message.id}-${index}`}
          role="status"
          className="flex items-center gap-2 rounded-md border border-border/60 bg-muted/20 px-3 py-2 text-sm"
        >
          <StatusIndicator kind="done" />
          <OryText message={message} />
        </div>
      ))}
    </div>
  );
}

/** What Kratos rejected in one field, under that field. */
export function FieldErrors({ messages }: { messages: UiText[] | undefined }) {
  return (
    <>
      {errorsOf(messages).map((message) => (
        <p key={message.id} role="alert" className="form-error">
          <OryText message={message} />
        </p>
      ))}
    </>
  );
}

/** A section's submit: tells Kratos which method the form is for, as Ory's own buttons do. */
export function MethodSubmit({
  method,
  ...props
}: Omit<ButtonProps, "type" | "name" | "value" | "onClick"> & {
  method: UiNodeGroupEnum;
}) {
  const {
    setValue,
    formState: { isSubmitting },
  } = useFormContext();

  return (
    <Button
      type="submit"
      size="sm"
      name="method"
      value={method}
      isLoading={isSubmitting}
      onClick={() => setValue("method", method)}
      {...props}
    />
  );
}
