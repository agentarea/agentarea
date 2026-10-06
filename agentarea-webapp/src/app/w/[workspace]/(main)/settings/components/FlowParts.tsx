"use client";

import type { UiNodeGroupEnum, UiText } from "@ory/client-fetch";
import { useComponents, useOryFlow } from "@ory/elements-react";
import { useFormContext } from "react-hook-form";
import FormError from "@/components/FormError";
import { Button, type ButtonProps } from "@/components/ui/button";
import { errorsOf } from "./oryNodes";

/** A Kratos message in the UI language, with its `ory/message/<id>` test id. */
export function OryText({ message }: { message: UiText }) {
  const { Message } = useComponents();
  return <Message.Content message={message} />;
}

/** Errors Kratos raised for the whole flow rather than for one field. */
export function FlowErrors() {
  const { flow } = useOryFlow();
  const errors = errorsOf(flow.ui.messages);
  if (errors.length === 0) return null;

  return (
    <div className="space-y-2">
      {errors.map((message, index) => (
        <FormError key={`${message.id}-${index}`}>
          <OryText message={message} />
        </FormError>
      ))}
    </div>
  );
}

/** Kratos' own success line, e.g. "Your changes have been saved!". */
export function FlowSuccess() {
  const { flow } = useOryFlow();

  return (
    <>
      {(flow.ui.messages ?? [])
        .filter((message) => message.type !== "error")
        .map((message, index) => (
          <span key={`${message.id}-${index}`} role="status">
            <OryText message={message} />
          </span>
        ))}
    </>
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
