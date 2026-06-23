// Copyright © 2024 Ory Corp
// SPDX-License-Identifier: Apache-2.0

import { UiText } from "@ory/client-fetch"
import { useIntl } from "react-intl"
import { resolveLabel } from "../../../../util/nodes"

type CheckboxLabelProps = {
  label?: UiText
}

const linkRegex = /\[([^\]]+)\]\(([^)]+)\)/g
const parenthesizedUrlRegex =
  /((?:[A-ZА-ЯЁ][^\s()]*)(?:\s+[A-Za-zА-Яа-яЁё][^\s()]*){0,4})\s*\(((?:https?:\/\/)?[^()\s]+\.[^()\s]+(?:\/[^()\s]*)?)\)/gu

function normalizeParenthesizedLinks(labelText: string) {
  return labelText.replace(
    parenthesizedUrlRegex,
    (_match, linkText: string, url: string) =>
      `[${linkText}](${url.startsWith("http") ? url : `https://${url}`})`,
  )
}

export function computeLabelElements(labelText: string) {
  const normalizedLabelText = normalizeParenthesizedLinks(labelText)
  const elements = []
  let lastIndex = 0

  // Use matchAll to find all markdown links
  for (const match of normalizedLabelText.matchAll(linkRegex)) {
    const linkText = match[1]
    const url = match[2]
    const matchStart = match.index
    if (typeof matchStart === "undefined") {
      // Some types seem to be wrong somewhere, eslint complains that matchStart can be undefined, but it can't?
      // So we just skip this match, if it is undefined
      continue
    }

    // Push the text before the match
    if (matchStart > lastIndex) {
      elements.push(normalizedLabelText.slice(lastIndex, matchStart))
    }

    // Push the <a> tag for the markdown link
    elements.push(
      <a
        key={matchStart}
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className="text-button-link-brand-brand underline hover:text-button-link-brand-brand-hover"
      >
        {linkText}
      </a>,
    )

    // Update lastIndex to the end of the current match
    lastIndex = matchStart + match[0].length
  }

  // Push any remaining text after the last match
  if (lastIndex < normalizedLabelText.length) {
    elements.push(normalizedLabelText.slice(lastIndex))
  }
  return elements
}

export function CheckboxLabel({ label }: CheckboxLabelProps) {
  const intl = useIntl()
  if (!label) {
    return null
  }

  const labelText = resolveLabel(label, intl)

  return <>{computeLabelElements(labelText)}</>
}
