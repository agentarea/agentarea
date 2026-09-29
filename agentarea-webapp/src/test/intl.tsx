import type { ReactNode } from "react";
import { NextIntlClientProvider } from "next-intl";
import messages from "../../messages/en.json";

/**
 * The app's real English messages, for a test that renders translated UI:
 * controls are found by the text a user sees, and a missing key fails like it
 * would in the app instead of hiding behind an identity mock.
 */
export function IntlProvider({ children }: { children: ReactNode }) {
  return (
    <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
      {children}
    </NextIntlClientProvider>
  );
}
