"use client";

import { useEffect, useState } from "react";

/**
 * Hook to track form submitting state via custom events
 * Only tracks state after successful validation (when handleFormSubmit is called)
 */
export function useFormSubmittingState(formId: string = "agent-form") {
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    const form = document.getElementById(formId);
    if (!form) return;

    const handleSubmittingChange = (e: Event) => {
      const customEvent = e as CustomEvent;
      setIsSubmitting(customEvent.detail.isSubmitting);
    };

    form.addEventListener("form-submitting", handleSubmittingChange as EventListener);

    // Check initial state
    setIsSubmitting(form.getAttribute("data-submitting") === "true");

    return () => {
      form.removeEventListener("form-submitting", handleSubmittingChange as EventListener);
    };
  }, [formId]);

  return isSubmitting;
}


/**
 * The form side of {@link useFormSubmittingState}: tells a header button that
 * targets `form` whether the form is saving.
 */
export function announceFormSubmitting(
  form: HTMLFormElement | null,
  isSubmitting: boolean
) {
  if (!form) return;
  if (isSubmitting) form.setAttribute("data-submitting", "true");
  else form.removeAttribute("data-submitting");
  form.dispatchEvent(
    new CustomEvent("form-submitting", { detail: { isSubmitting } })
  );
}
