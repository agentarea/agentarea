// Copyright © 2023 Ory Corp
// SPDX-License-Identifier: Apache-2.0

// Ory ships ~86 locale files upstream. `OryLocales` is indexed dynamically at
// runtime, so every imported locale is retained by the bundler regardless of
// which one is selected. Only the locales the app actually offers are kept.

import { default as en } from "./en.json"
import { default as ru } from "./ru.json"

export type LocaleMap = Record<string, Record<string, string>>

export const OryLocales: LocaleMap = Object.freeze({
  en,
  ru,
})
