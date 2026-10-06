"use client";

import { useEffect, useRef, useState } from "react";
import type { UiNode, UiNodeGroupEnum, UiText } from "@ory/client-fetch";
import { useComponents, useOryFlow } from "@ory/elements-react";
import { useFormContext } from "react-hook-form";
import FormError from "@/components/FormError";
import { Button, type ButtonProps } from "@/components/ui/button";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { accepted, errorsOf } from "./oryNodes";

/** A Kratos message in the UI language, with its `ory/message/<id>` test id. */
export function OryText({ message }: { message: UiText }) {
  const { Message } = useComponents();
  return <Message.Content message={message} />;
}

/** Kratos' success line ("Your changes have been saved!") for the current flow. */
function successMessages(flow: {
  state: unknown;
  ui: { messages?: UiText[] };
}) {
  const messages = flow.ui.messages ?? [];
  return flow.state === "success" && errorsOf(messages).length === 0
    ? messages.filter((message) => message.type !== "error")
    : [];
}

/**
 * What Kratos says about the whole flow: its errors, and the success line of a
 * flow the page opened with — after the provider sends you back from linking
 * an account, say. A save made on the page reports in its own section.
 */
export function FlowMessages() {
  const { flow } = useOryFlow();
  const [openedWith] = useState(flow);
  const errors = errorsOf(flow.ui.messages);
  const success = flow === openedWith ? successMessages(flow) : [];
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

/** The same success line inline, where a section reports its own save. */
export function FlowSuccess() {
  const { flow } = useOryFlow();

  return (
    <>
      {successMessages(flow).map((message, index) => (
        <span key={`${message.id}-${index}`} role="status">
          <OryText message={message} />
        </span>
      ))}
    </>
  );
}

/**
 * Whether the flow on screen is the one this section's own last submit came
 * back with, and Kratos took it. A save in another section replaces the flow,
 * so this section stops claiming it.
 */
export function useSavedHere(nodes: UiNode[]) {
  const { flow } = useOryFlow();
  const {
    formState: { isSubmitting, isSubmitSuccessful },
  } = useFormContext();
  const [savedFlow, setSavedFlow] = useState<typeof flow | null>(null);
  const submitting = useRef(false);

  useEffect(() => {
    if (isSubmitting) {
      submitting.current = true;
      return;
    }
    if (!submitting.current) return;
    submitting.current = false;
    setSavedFlow(isSubmitSuccessful && accepted(flow, nodes) ? flow : null);
  }, [isSubmitting, isSubmitSuccessful, flow, nodes]);

  return savedFlow !== null && savedFlow === flow;
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
