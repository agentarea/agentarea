"use client";

import { type FormEvent, type ReactNode, useCallback, useState } from "react";
import { LoadingSpinner } from "@/components/LoadingSpinner";

const SOCIAL_PROVIDERS = ["google", "github"];

function isSocialSubmitter(
  submitter: HTMLElement | null,
): submitter is HTMLButtonElement | HTMLInputElement {
  if (
    !(submitter instanceof HTMLButtonElement) &&
    !(submitter instanceof HTMLInputElement)
  ) {
    return false;
  }

  const searchableValues = [
    submitter.getAttribute("name"),
    submitter.getAttribute("value"),
    submitter.getAttribute("aria-label"),
    submitter.getAttribute("data-testid"),
  ]
    .filter(Boolean)
    .map((value) => value!.toLowerCase());

  return SOCIAL_PROVIDERS.some((provider) =>
    searchableValues.some((value) => value.includes(provider)),
  );
}

export function AuthSocialLoadingOverlay({
  children,
}: {
  children: ReactNode;
}) {
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmitCapture = useCallback((event: FormEvent<HTMLDivElement>) => {
    const nativeEvent = event.nativeEvent;
    const submitter =
      nativeEvent instanceof SubmitEvent ? nativeEvent.submitter : null;

    if (isSocialSubmitter(submitter)) {
      setIsLoading(true);
    }
  }, []);

  return (
    <div className="relative" onSubmitCapture={handleSubmitCapture}>
      {children}
      {isLoading ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm">
          <LoadingSpinner size="lg" />
        </div>
      ) : null}
    </div>
  );
}
